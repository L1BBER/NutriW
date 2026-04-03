package com.example.nutriw.data.repo

import com.example.nutriw.data.api.NetworkModule
import com.example.nutriw.data.api.ConfirmProductsRequest
import com.example.nutriw.data.api.ConfirmProductsResponse
import com.example.nutriw.data.api.ScanResponse
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File

class ScanRepository {
    suspend fun scanFile(file: File): ScanResponse {
        val req = file.asRequestBody("image/jpeg".toMediaType())
        val part = MultipartBody.Part.createFormData("image", file.name, req)
        return NetworkModule.api.scanPhoto(part)
    }

    suspend fun confirmProducts(body: ConfirmProductsRequest): ConfirmProductsResponse {
        return NetworkModule.api.confirmProducts(body)
    }
}
