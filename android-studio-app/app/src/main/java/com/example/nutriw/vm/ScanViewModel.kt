package com.example.nutriw.vm

import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.nutriw.data.api.ProductCandidate
import com.example.nutriw.data.api.RecipeItem
import com.example.nutriw.data.api.ResolvedServer
import com.example.nutriw.data.api.ScanResponse
import com.example.nutriw.data.api.ConfirmProductsRequest
import com.example.nutriw.data.api.EditableProductPayload
import com.example.nutriw.data.repo.ScanRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.io.File

enum class ScanFlow {
    HOME,
    CAMERA,
    PRODUCTS,
    RECIPES
}

data class EditableProduct(
    val name: String,
    val amount: String,
    val brand: String? = null,
    val confidence: Double? = null,
    val candidates: List<ProductCandidate> = emptyList(),
    val ocrText: String = ""
)

enum class ServerConnectionStatus {
    SEARCHING,
    CONNECTED,
    OFFLINE
}

data class ServerUiState(
    val status: ServerConnectionStatus = ServerConnectionStatus.SEARCHING,
    val message: String = "Searching for server...",
    val baseUrl: String? = null
)

sealed class ScanUiState {
    data object Idle : ScanUiState()
    data object Loading : ScanUiState()
    data class Success(val data: ScanResponse) : ScanUiState()
    data class Error(val message: String) : ScanUiState()
}

class ScanViewModel(
    application: Application
) : AndroidViewModel(application) {

    private val repo = ScanRepository(application.applicationContext)

    private val _state = MutableStateFlow<ScanUiState>(ScanUiState.Idle)
    val state: StateFlow<ScanUiState> = _state

    var flow: ScanFlow by mutableStateOf(ScanFlow.HOME)
        private set

    var capturedImageBitmap: Bitmap? by mutableStateOf(null)
        private set

    var isLoading: Boolean by mutableStateOf(false)
        private set

    var errorMessage: String? by mutableStateOf(null)
        private set

    var editableProducts: List<EditableProduct> by mutableStateOf(emptyList())
        private set

    var recipes: List<RecipeItem> by mutableStateOf(emptyList())
        private set

    var lastScanResponse: ScanResponse? by mutableStateOf(null)
        private set

    var serverState: ServerUiState by mutableStateOf(
        value = repo.lastKnownServerUrl()?.let {
            ServerUiState(
                status = ServerConnectionStatus.SEARCHING,
                message = "Checking last connected server...",
                baseUrl = it
            )
        } ?: ServerUiState()
    )
        private set

    var isDiscoveringServer: Boolean by mutableStateOf(false)
        private set

    val canOpenRecipes: Boolean
        get() = recipes.isNotEmpty() || flow == ScanFlow.RECIPES

    init {
        refreshServer()
    }

    fun refreshServer() {
        if (isDiscoveringServer) return

        isDiscoveringServer = true
        serverState = serverState.copy(
            status = ServerConnectionStatus.SEARCHING,
            message = "Searching USB, emulator, and local network..."
        )

        viewModelScope.launch {
            val resolved = repo.discoverServer()
            if (resolved != null) {
                applyResolvedServer(resolved)
            } else {
                serverState = ServerUiState(
                    status = ServerConnectionStatus.OFFLINE,
                    message = "Server not found. Connect USB reverse or use the same Wi-Fi network.",
                    baseUrl = null
                )
            }
            isDiscoveringServer = false
        }
    }

    fun scan(file: File) {
        errorMessage = null
        capturedImageBitmap = decodeBitmapRespectingExif(file)
        isLoading = true
        _state.value = ScanUiState.Loading

        viewModelScope.launch {
            try {
                val result = repo.scanFile(file)
                val res = result.data
                applyResolvedServer(result.server)
                _state.value = ScanUiState.Success(res)
                isLoading = false

                lastScanResponse = res
                editableProducts = res.products.map {
                    EditableProduct(
                        name = it.name,
                        amount = it.amount ?: it.fields?.net.orEmpty(),
                        brand = it.brand,
                        confidence = it.confidence,
                        candidates = it.candidates,
                        ocrText = it.fields?.ocrText.orEmpty()
                    )
                }
                recipes = res.recipes
                flow = ScanFlow.PRODUCTS
            } catch (e: Exception) {
                _state.value = ScanUiState.Error(e.message ?: "Network/Server error")
                isLoading = false
                errorMessage = e.message ?: "Network/Server error"
            }
        }
    }

    fun scanAgain() {
        _state.value = ScanUiState.Idle
        isLoading = false
        flow = ScanFlow.CAMERA
        capturedImageBitmap = null
        editableProducts = emptyList()
        recipes = emptyList()
        lastScanResponse = null
        errorMessage = null
    }

    fun updateProductName(index: Int, value: String) {
        editableProducts = editableProducts.mapIndexed { i, p ->
            if (i == index) p.copy(name = value) else p
        }
    }

    fun updateProductAmount(index: Int, value: String) {
        editableProducts = editableProducts.mapIndexed { i, p ->
            if (i == index) p.copy(amount = value) else p
        }
    }

    fun confirmProducts() {
        errorMessage = null
        isLoading = true
        viewModelScope.launch {
            try {
                val body = ConfirmProductsRequest(
                    products = editableProducts.map { EditableProductPayload(it.name, it.amount) }
                )
                val result = repo.confirmProducts(body)
                applyResolvedServer(result.server)
                recipes = result.data.recipes
                isLoading = false
                flow = ScanFlow.RECIPES
            } catch (e: Exception) {
                isLoading = false
                errorMessage = e.message ?: "Network/Server error"
            }
        }
    }

    fun openRecipes() {
        if (canOpenRecipes) flow = ScanFlow.RECIPES
    }

    fun openProducts() {
        if (editableProducts.isNotEmpty()) {
            flow = ScanFlow.PRODUCTS
        }
    }

    fun reportCaptureError(message: String) {
        errorMessage = message
    }

    fun openHome() {
        flow = ScanFlow.HOME
    }

    fun openCamera() {
        errorMessage = null
        capturedImageBitmap = null
        _state.value = ScanUiState.Idle
        flow = ScanFlow.CAMERA
    }

    private fun applyResolvedServer(server: ResolvedServer) {
        serverState = ServerUiState(
            status = ServerConnectionStatus.CONNECTED,
            message = "Connected via ${server.source}",
            baseUrl = server.baseUrl
        )
    }

    private fun decodeBitmapRespectingExif(file: File): Bitmap? {
        val bmp = BitmapFactory.decodeFile(file.absolutePath) ?: return null
        return try {
            val exif = ExifInterface(file.absolutePath)
            val orientation = exif.getAttributeInt(
                ExifInterface.TAG_ORIENTATION,
                ExifInterface.ORIENTATION_NORMAL
            )
            val rotationDegrees = when (orientation) {
                ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                else -> 0f
            }
            if (rotationDegrees == 0f) bmp
            else {
                val m = Matrix().apply { postRotate(rotationDegrees) }
                Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, m, true)
            }
        } catch (_: Exception) {
            bmp
        }
    }
}
