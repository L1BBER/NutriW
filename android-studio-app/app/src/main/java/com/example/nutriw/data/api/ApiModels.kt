package com.example.nutriw.data.api

data class ScanResponse(
    val products: List<ProductItem> = emptyList(),
    val recipes: List<RecipeItem> = emptyList(),
    val warnings: List<String> = emptyList(),
    val need_user_review: Boolean? = null
)

data class ProductItem(
    val name: String,
    val dietaryLabels: List<String> = emptyList(),
    val amount: String? = null,
    val confidence: Double? = null,
    val candidates: List<ProductCandidate> = emptyList(),
    val fields: ProductFields? = null
)

data class RecipeItem(
    val id: Int? = null,
    val titlePl: String,
    val missing: List<String> = emptyList(),
    val coverage: Double? = null,
    val dietaryLabels: List<String> = emptyList(),
    val servings: Int? = null,
    val kcalPerPortion: Double? = null
)

data class ProductCandidate(
    val id: Int? = null,
    val name: String,
    val aliases: List<String> = emptyList(),
    val pieces: Int? = null,
    val volume_l: Double? = null,
    val weight_g: Double? = null,
    val confidence: Double? = null,
    val image_score: Double? = null,
    val text_score: Double? = null,
    val measurement_score: Double? = null,
    val sample_count: Int? = null
)

data class ProductFields(
    val ocrText: String? = null,
    val net: String? = null,
    val fat_percent: Double? = null,
    val kcal_100: Double? = null,
    val p_100: Double? = null,
    val f_100: Double? = null,
    val c_100: Double? = null
)

data class ConfirmProductsRequest(
    val products: List<EditableProductPayload>
)

data class EditableProductPayload(
    val name: String,
    val amount: String? = null
)

data class ConfirmProductsResponse(
    val recipes: List<RecipeItem> = emptyList()
)
