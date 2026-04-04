package com.example.nutriw.data.repo

import android.content.Context
import com.example.nutriw.data.api.NetworkModule
import com.example.nutriw.data.api.ConfirmProductsRequest
import com.example.nutriw.data.api.ConfirmProductsResponse
import com.example.nutriw.data.api.ResolvedServer
import com.example.nutriw.data.api.ScanResponse
import com.example.nutriw.data.api.ServerCallResult
import com.example.nutriw.data.api.ServerDiscovery
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File

class ScanRepository(context: Context) {

    private val serverDiscovery = ServerDiscovery(context)

    fun lastKnownServerUrl(): String? = serverDiscovery.lastKnownBaseUrl()

    suspend fun discoverServer(): ResolvedServer? = serverDiscovery.discover()

    suspend fun scanFile(file: File): ServerCallResult<ScanResponse> {
        val req = file.asRequestBody("image/jpeg".toMediaType())
        val part = MultipartBody.Part.createFormData("image", file.name, req)
        return executeWithResolvedServer { api ->
            api.scanPhoto(part)
        }
    }

    suspend fun confirmProducts(body: ConfirmProductsRequest): ServerCallResult<ConfirmProductsResponse> {
        return executeWithResolvedServer { api ->
            api.confirmProducts(body)
        }
    }

    private suspend fun <T> executeWithResolvedServer(
        call: suspend (api: com.example.nutriw.data.api.ScanApi) -> T
    ): ServerCallResult<T> {
        val initialServer = serverDiscovery.lastKnownBaseUrl()?.let {
            ResolvedServer(it, "Last connected")
        } ?: serverDiscovery.discover()
        ?: throw IllegalStateException("Server not found. Connect USB reverse or use the same Wi-Fi network and try again.")

        return try {
            val result = call(NetworkModule.api(initialServer.baseUrl))
            serverDiscovery.remember(initialServer.baseUrl)
            ServerCallResult(initialServer, result)
        } catch (firstError: Exception) {
            val rediscoveredServer = serverDiscovery.discover()
            if (rediscoveredServer != null && rediscoveredServer.baseUrl != initialServer.baseUrl) {
                val retryResult = call(NetworkModule.api(rediscoveredServer.baseUrl))
                serverDiscovery.remember(rediscoveredServer.baseUrl)
                ServerCallResult(rediscoveredServer, retryResult)
            } else {
                throw firstError
            }
        }
    }
}
