package com.example.nutriw.data.api

import okhttp3.MultipartBody
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Body

interface ScanApi {
    @Multipart
    @POST("/scan/confirm")
    suspend fun scanPhoto(@Part image: MultipartBody.Part): ScanResponse

    @POST("/scan/confirm_user_edit")
    suspend fun confirmProducts(@Body body: ConfirmProductsRequest): ConfirmProductsResponse
}
