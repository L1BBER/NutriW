package com.example.nutriw.data.api

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import okhttp3.Request
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.Collections
import java.util.LinkedHashMap
import java.util.concurrent.TimeUnit

data class ResolvedServer(
    val baseUrl: String,
    val source: String
)

data class ServerCallResult<T>(
    val server: ResolvedServer,
    val data: T
)

class ServerDiscovery(context: Context) {

    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val probeClient = NetworkModule.client.newBuilder()
        .connectTimeout(350, TimeUnit.MILLISECONDS)
        .readTimeout(350, TimeUnit.MILLISECONDS)
        .writeTimeout(350, TimeUnit.MILLISECONDS)
        .callTimeout(500, TimeUnit.MILLISECONDS)
        .build()

    fun lastKnownBaseUrl(): String? {
        return prefs.getString(KEY_LAST_URL, null)?.takeIf { it.isNotBlank() }
    }

    fun remember(baseUrl: String) {
        prefs.edit()
            .putString(KEY_LAST_URL, baseUrl.trim().removeSuffix("/"))
            .apply()
    }

    suspend fun discover(): ResolvedServer? = withContext(Dispatchers.IO) {
        val candidates = buildCandidates()
        if (candidates.isEmpty()) {
            return@withContext null
        }

        val directProbe = candidates.take(3)
        for (candidate in directProbe) {
            if (probe(candidate.baseUrl)) {
                remember(candidate.baseUrl)
                return@withContext candidate
            }
        }

        val networkCandidates = candidates.drop(directProbe.size)
        for (batch in networkCandidates.chunked(24)) {
            val discovered = coroutineScope {
                batch.map { candidate ->
                    async {
                        if (probe(candidate.baseUrl)) candidate else null
                    }
                }.awaitAll().firstOrNull { it != null }
            }
            if (discovered != null) {
                remember(discovered.baseUrl)
                return@withContext discovered
            }
        }

        null
    }

    private fun buildCandidates(): List<ResolvedServer> {
        val ordered = LinkedHashMap<String, ResolvedServer>()

        lastKnownBaseUrl()?.let { baseUrl ->
            ordered[baseUrl] = ResolvedServer(baseUrl, "Last connected")
        }

        ordered["http://127.0.0.1:8000"] = ResolvedServer("http://127.0.0.1:8000", "USB reverse")
        ordered["http://10.0.2.2:8000"] = ResolvedServer("http://10.0.2.2:8000", "Android Emulator")

        localSubnetCandidates().forEach { baseUrl ->
            ordered.putIfAbsent(baseUrl, ResolvedServer(baseUrl, "Local network"))
        }

        return ordered.values.toList()
    }

    private fun localSubnetCandidates(): List<String> {
        val localIp = findLocalIpv4Address() ?: return emptyList()
        val prefix = localIp.substringBeforeLast(".", missingDelimiterValue = "")
        if (prefix.isBlank()) return emptyList()

        val selfOctet = localIp.substringAfterLast(".", missingDelimiterValue = "").toIntOrNull()
        val orderedHosts = LinkedHashMap<Int, Unit>()

        listOf(1, 2, 10, 20, 50, 100, 101, 102, 110, 150, 200).forEach { host ->
            if (host in 1..254 && host != selfOctet) {
                orderedHosts[host] = Unit
            }
        }

        for (host in 1..254) {
            if (host != selfOctet) {
                orderedHosts.putIfAbsent(host, Unit)
            }
        }

        return orderedHosts.keys.map { host -> "http://$prefix.$host:8000" }
    }

    private fun findLocalIpv4Address(): String? {
        val interfaces = try {
            Collections.list(NetworkInterface.getNetworkInterfaces())
        } catch (_: Exception) {
            emptyList()
        }

        return interfaces
            .filter { network ->
                try {
                    network.isUp && !network.isLoopback && !network.isVirtual
                } catch (_: Exception) {
                    false
                }
            }
            .flatMap { network ->
                try {
                    Collections.list(network.inetAddresses)
                } catch (_: Exception) {
                    emptyList()
                }
            }
            .firstOrNull { address ->
                address is Inet4Address && address.isSiteLocalAddress && !address.isLoopbackAddress
            }
            ?.hostAddress
    }

    private fun probe(baseUrl: String): Boolean {
        return try {
            val request = Request.Builder()
                .url("${NetworkModule.normalizeBaseUrl(baseUrl)}health")
                .get()
                .build()

            probeClient.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty().replace(" ", "")
                response.isSuccessful && body.contains("\"ok\":true")
            }
        } catch (_: Exception) {
            false
        }
    }

    private companion object {
        const val PREFS_NAME = "nutriw_server_discovery"
        const val KEY_LAST_URL = "last_base_url"
    }
}
