package com.example.nutriw.ui.screens

import android.Manifest
import android.content.Context
import android.graphics.BitmapFactory
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.*
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.nutriw.data.api.ProductCandidate
import com.example.nutriw.data.api.RecipeItem
import com.example.nutriw.vm.ScanFlow
import com.example.nutriw.vm.ScanViewModel
import com.example.nutriw.vm.ServerConnectionStatus
import com.example.nutriw.vm.recipeDietaryFilterOptions
import java.io.File
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.Executor

@Composable
fun RootScreen(isDark: Boolean, onToggleTheme: () -> Unit, vm: ScanViewModel = viewModel()) {
    var menuOpen by remember { mutableStateOf(false) }
    var showSettings by remember { mutableStateOf(false) }
    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(MaterialTheme.colorScheme.background, MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.82f), MaterialTheme.colorScheme.background)))) {
        if (vm.flow == ScanFlow.CAMERA) {
            CameraScanScreen(vm)
        } else {
            Scaffold(
                containerColor = Color.Transparent,
                contentWindowInsets = WindowInsets(0),
                topBar = { TopBar(vm, menuOpen, { menuOpen = true }, { menuOpen = false }, { showSettings = true }) }
            ) { pad ->
                AnimatedContent(targetState = vm.flow, transitionSpec = { fadeIn(tween(220)) togetherWith fadeOut(tween(180)) }, label = "flow") { flow ->
                    when (flow) {
                        ScanFlow.HOME -> HomeScreen(vm, pad)
                        ScanFlow.PRODUCTS -> ProductsScreen(vm, pad)
                        ScanFlow.RECIPES -> RecipesScreen(vm, pad)
                        ScanFlow.CAMERA -> Unit
                    }
                }
            }
        }
    }
    if (showSettings) SettingsDialog(isDark, vm.serverState.message, vm.serverState.baseUrl, vm.isDiscoveringServer, { vm.refreshServer() }, onToggleTheme, { showSettings = false })
}

@Composable
private fun TopBar(vm: ScanViewModel, menuOpen: Boolean, onMenuOpen: () -> Unit, onMenuDismiss: () -> Unit, onOpenSettings: () -> Unit) {
    Surface(modifier = Modifier.fillMaxWidth().statusBarsPadding().padding(12.dp), shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 14.dp), Arrangement.SpaceBetween, Alignment.CenterVertically) {
            Column { Text("NutriW", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold); Text("Mobile scanner", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Box {
                IconButton(onClick = onMenuOpen) { Icon(Icons.Default.MoreVert, contentDescription = "Menu") }
                DropdownMenu(expanded = menuOpen, onDismissRequest = onMenuDismiss) {
                    DropdownMenuItem(text = { Text("Home") }, onClick = { onMenuDismiss(); vm.openHome() })
                    DropdownMenuItem(text = { Text("Open camera") }, onClick = { onMenuDismiss(); vm.openCamera() })
                    DropdownMenuItem(text = { Text("Open products") }, enabled = vm.editableProducts.isNotEmpty(), onClick = { onMenuDismiss(); vm.openProducts() })
                    DropdownMenuItem(text = { Text("Open recipes") }, enabled = vm.canOpenRecipes, onClick = { onMenuDismiss(); vm.openRecipes() })
                    DropdownMenuItem(text = { Text("Find server again") }, onClick = { onMenuDismiss(); vm.refreshServer() })
                    DropdownMenuItem(text = { Text("Settings") }, onClick = { onMenuDismiss(); onOpenSettings() })
                }
            }
        }
    }
}

@Composable
private fun HomeScreen(vm: ScanViewModel, pad: PaddingValues) {
    Column(Modifier.fillMaxSize().padding(pad).padding(horizontal = 16.dp, vertical = 12.dp)) {
        LazyColumn(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(bottom = 20.dp)) {
            item { HeroCard("Scan products with NutriW", "Open the camera, capture a product, confirm or edit the result, and then get matching recipes from the recognized items.") }
            item { ServerCard(vm.serverState.status, vm.serverState.message, vm.serverState.baseUrl, vm.isDiscoveringServer, { vm.refreshServer() }) }
            item { InfoCard("What this app does", listOf("Recognizes products from photos.", "Uses the upgraded server-side ranking pipeline.", "Lets you confirm or edit the detected product.", "Shows recipes after product confirmation.")) }
        }
        Button(onClick = { vm.openCamera() }, modifier = Modifier.fillMaxWidth().height(58.dp)) {
            Icon(Icons.Default.CameraAlt, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Open Camera")
        }
    }
}

@Composable
private fun CameraScanScreen(vm: ScanViewModel) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var hasPermission by remember { mutableStateOf(false) }
    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { hasPermission = it }
    LaunchedEffect(Unit) { launcher.launch(Manifest.permission.CAMERA) }
    Box(Modifier.fillMaxSize()) {
        if (hasPermission) {
            vm.capturedImageBitmap?.let {
                Image(it.asImageBitmap(), contentDescription = "Captured", modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            } ?: AndroidView(factory = { ctx ->
                PreviewView(ctx).also { pv ->
                    val future = ProcessCameraProvider.getInstance(ctx)
                    future.addListener({
                        val provider = future.get()
                        val preview = Preview.Builder().build().also { it.setSurfaceProvider(pv.surfaceProvider) }
                        val capture = ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).build()
                        imageCapture = capture
                        try {
                            provider.unbindAll()
                            provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, capture)
                        } catch (e: Exception) {
                            Log.e("CameraScanScreen", "Camera bind failed", e)
                            vm.reportCaptureError("Unable to connect to the camera.")
                        }
                    }, ctx.mainExecutor())
                }
            }, modifier = Modifier.fillMaxSize())
        } else {
            Box(Modifier.fillMaxSize().background(Color.Black))
        }
        Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.18f), Color.Transparent, Color.Black.copy(alpha = 0.5f)))))
        if (vm.isLoading) ScanningOverlay()
        Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 14.dp, vertical = 12.dp), Arrangement.SpaceBetween, Alignment.CenterVertically) {
            Surface(color = MaterialTheme.colorScheme.surface.copy(alpha = 0.88f), shape = RoundedCornerShape(18.dp)) {
                IconButton(onClick = { vm.openHome() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
            }
            AssistChip(onClick = {}, enabled = false, label = { Text(cameraStatus(vm.serverState.status)) }, colors = AssistChipDefaults.assistChipColors(disabledContainerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.88f), disabledLabelColor = MaterialTheme.colorScheme.onSurface))
        }
        if (!hasPermission) {
            Surface(modifier = Modifier.align(Alignment.Center).padding(22.dp), shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f)) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("Camera permission is required", style = MaterialTheme.typography.titleMedium)
                    Text("Allow camera access to start scanning.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    FilledTonalButton(onClick = { launcher.launch(Manifest.permission.CAMERA) }) { Text("Grant permission") }
                }
            }
        }
        vm.errorMessage?.let { msg ->
            Surface(modifier = Modifier.align(Alignment.TopCenter).padding(top = 88.dp, start = 16.dp, end = 16.dp), shape = RoundedCornerShape(18.dp), color = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f)) {
                Row(Modifier.padding(horizontal = 14.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Warning, contentDescription = null, tint = MaterialTheme.colorScheme.tertiary)
                    Text(msg)
                }
            }
        }
        if (!vm.isLoading && hasPermission) {
            Button(
                onClick = {
                    val capture = imageCapture ?: return@Button
                    takePhoto(context, capture, { vm.scan(it) }, { vm.reportCaptureError(it) })
                },
                shape = CircleShape,
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 34.dp).height(74.dp).widthIn(min = 190.dp)
            ) {
                Icon(Icons.Default.CameraAlt, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Scan")
            }
        }
    }
}

@Composable
private fun ProductsScreen(vm: ScanViewModel, pad: PaddingValues) {
    val response = vm.lastScanResponse
    Column(Modifier.fillMaxSize().padding(pad).padding(horizontal = 16.dp, vertical = 12.dp)) {
        LazyColumn(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(bottom = 20.dp)) {
            item { HeroCard("Confirm or edit the product", if (response?.need_user_review == false) "The recognizer is confident, but you can still adjust the result before recipes." else "Review the result carefully and fix it if needed before continuing.") }
            response?.warnings?.forEach { item { WarningCard(it) } }
            vm.capturedImageBitmap?.let { bmp ->
                item { Card(shape = RoundedCornerShape(26.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f))) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) { Text("Captured image", style = MaterialTheme.typography.titleMedium); Image(bmp.asImageBitmap(), contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxWidth().height(180.dp).clip(RoundedCornerShape(20.dp))) } } }
            }
            itemsIndexed(vm.editableProducts) { index, product ->
                Card(shape = RoundedCornerShape(26.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f))) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween, Alignment.CenterVertically) {
                            Column { Text("Detected product ${index + 1}", style = MaterialTheme.typography.titleMedium) }
                            product.confidence?.let { AssistChip(onClick = {}, enabled = false, label = { Text("${(it * 100).toInt()}% confidence") }, leadingIcon = { Icon(Icons.Default.AutoAwesome, contentDescription = null) }, colors = AssistChipDefaults.assistChipColors(disabledContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.12f), disabledLabelColor = MaterialTheme.colorScheme.primary, disabledLeadingIconContentColor = MaterialTheme.colorScheme.primary)) }
                        }
                        OutlinedTextField(value = product.name, onValueChange = { vm.updateProductName(index, it) }, label = { Text("Product name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(value = product.amount, onValueChange = { vm.updateProductAmount(index, it) }, label = { Text("Detected amount") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                        if (product.candidates.isNotEmpty()) {
                            Text("Top AI candidates", style = MaterialTheme.typography.titleMedium)
                            LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                items(product.candidates.take(4)) { candidate ->
                                    AssistChip(
                                        onClick = {
                                            vm.updateProductName(index, candidate.name)
                                            candidateMeasurementLabel(candidate)?.let { vm.updateProductAmount(index, it) }
                                        },
                                        label = { Text(candidateLabel(candidate)) },
                                        leadingIcon = { Icon(Icons.Default.AutoAwesome, contentDescription = null) },
                                        colors = AssistChipDefaults.assistChipColors(containerColor = MaterialTheme.colorScheme.surfaceVariant, labelColor = MaterialTheme.colorScheme.onSurface, leadingIconContentColor = MaterialTheme.colorScheme.primary)
                                    )
                                }
                            }
                        }
                        if (product.ocrText.isNotBlank()) Surface(color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.74f), shape = RoundedCornerShape(18.dp)) { Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) { Text("OCR snippet", style = MaterialTheme.typography.labelLarge); Text(product.ocrText.take(220), color = MaterialTheme.colorScheme.onSurfaceVariant) } }
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = { vm.scanAgain() }, modifier = Modifier.weight(1f)) { Text("Scan Again") }
            Button(onClick = { vm.confirmProducts() }, enabled = vm.editableProducts.isNotEmpty() && !vm.isLoading, modifier = Modifier.weight(1f)) {
                if (vm.isLoading) CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp) else Icon(Icons.Default.CheckCircle, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Get Recipes")
            }
        }
    }
}

@Composable
private fun RecipesScreen(vm: ScanViewModel, pad: PaddingValues) {
    val filteredRecipes = vm.filteredRecipes
    Column(Modifier.fillMaxSize().padding(pad).padding(horizontal = 16.dp, vertical = 12.dp)) {
        LazyColumn(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(14.dp), contentPadding = PaddingValues(bottom = 20.dp)) {
            item { HeroCard("Recipes", "These recipes are based on the products you confirmed in the previous step.") }
            item { RecipeFiltersCard(vm) }
            if (vm.recipes.isEmpty()) {
                item { WarningCard("No recipes are available yet. Confirm products first or add more recipes in the admin panel.") }
            } else if (filteredRecipes.isEmpty()) {
                item { WarningCard("No recipes match the selected dietary filters. Clear one or more filters and try again.") }
            } else {
                items(filteredRecipes) { RecipeCard(it) }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = { vm.openProducts() }, enabled = vm.editableProducts.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Back") }
            Button(onClick = { vm.scanAgain() }, modifier = Modifier.weight(1f)) { Icon(Icons.Default.CameraAlt, contentDescription = null); Spacer(Modifier.width(8.dp)); Text("New Scan") }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RecipeFiltersCard(vm: ScanViewModel) {
    Card(shape = RoundedCornerShape(26.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f))) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Dietary filters", style = MaterialTheme.typography.titleMedium)
                    Text("Choose one or more labels to narrow the recipe list.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (vm.selectedRecipeFilters.isNotEmpty()) {
                    TextButton(onClick = { vm.clearRecipeFilters() }) { Text("Clear") }
                }
            }
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                recipeDietaryFilterOptions.forEach { label ->
                    FilterChip(
                        selected = label in vm.selectedRecipeFilters,
                        onClick = { vm.toggleRecipeFilter(label) },
                        label = { Text(label) },
                        leadingIcon = { Text(dietaryLabelIcon(label)) }
                    )
                }
            }
        }
    }
}

@Composable
private fun HeroCard(title: String, subtitle: String) {
    Card(shape = RoundedCornerShape(28.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f))) {
        Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            AssistChip(onClick = {}, enabled = false, label = { Text("NutriW flow") }, leadingIcon = { Icon(Icons.Default.AutoAwesome, contentDescription = null) }, colors = AssistChipDefaults.assistChipColors(disabledContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.12f), disabledLabelColor = MaterialTheme.colorScheme.primary, disabledLeadingIconContentColor = MaterialTheme.colorScheme.primary))
            Text(title, style = MaterialTheme.typography.headlineMedium)
            Text(subtitle, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun ServerCard(status: ServerConnectionStatus, message: String, baseUrl: String?, loading: Boolean, onRefresh: () -> Unit) {
    val dot = when (status) {
        ServerConnectionStatus.CONNECTED -> Color(0xFF2FA89A)
        ServerConnectionStatus.SEARCHING -> MaterialTheme.colorScheme.tertiary
        ServerConnectionStatus.OFFLINE -> MaterialTheme.colorScheme.error
    }
    Card(shape = RoundedCornerShape(26.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f))) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) { Box(Modifier.size(12.dp).clip(CircleShape).background(dot)); Text("Server connection", style = MaterialTheme.typography.titleMedium) }
            Text(message, color = MaterialTheme.colorScheme.onSurfaceVariant)
            baseUrl?.let { Text(it, color = MaterialTheme.colorScheme.primary, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            FilledTonalButton(onClick = onRefresh, enabled = !loading) {
                if (loading) CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp) else Icon(Icons.Default.Refresh, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Refresh Connection")
            }
        }
    }
}

@Composable
private fun InfoCard(title: String, lines: List<String>) {
    Card(shape = RoundedCornerShape(26.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f))) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            lines.forEach { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }
}

@Composable
private fun WarningCard(text: String) {
    Card(shape = RoundedCornerShape(22.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiary.copy(alpha = 0.12f))) {
        Row(Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.Warning, contentDescription = null, tint = MaterialTheme.colorScheme.tertiary)
            Text(text)
        }
    }
}

@Composable
private fun RecipeCard(recipe: RecipeItem) {
    Card(shape = RoundedCornerShape(26.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f))) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween, Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { Text(recipe.titlePl, style = MaterialTheme.typography.titleLarge); recipe.servings?.let { Text("$it servings", color = MaterialTheme.colorScheme.onSurfaceVariant) } }
                Icon(Icons.Default.RestaurantMenu, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            }
            if (recipe.dietaryLabels.isNotEmpty()) {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(recipe.dietaryLabels) { label ->
                        AssistChip(
                            onClick = {},
                            enabled = false,
                            label = { Text(label) },
                            leadingIcon = { Text(dietaryLabelIcon(label)) },
                            colors = AssistChipDefaults.assistChipColors(
                                disabledContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.1f),
                                disabledLabelColor = MaterialTheme.colorScheme.primary,
                                disabledLeadingIconContentColor = MaterialTheme.colorScheme.primary
                            )
                        )
                    }
                }
            }
            recipe.coverage?.let { coverage ->
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Match ${(coverage * 100).toInt()}%", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    LinearProgressIndicator(progress = { coverage.toFloat() }, modifier = Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(999.dp)))
                }
            }
            if (recipe.missing.isNotEmpty()) {
                Surface(color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.74f), shape = RoundedCornerShape(18.dp)) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text("Need to buy", style = MaterialTheme.typography.labelLarge)
                        recipe.missing.forEach { Text("- $it", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                }
            } else {
                AssistChip(onClick = {}, enabled = false, label = { Text("Everything needed is already recognized") }, leadingIcon = { Icon(Icons.Default.CheckCircle, contentDescription = null) }, colors = AssistChipDefaults.assistChipColors(disabledContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.1f), disabledLabelColor = MaterialTheme.colorScheme.primary, disabledLeadingIconContentColor = MaterialTheme.colorScheme.primary))
            }
        }
    }
}

@Composable
private fun ScanningOverlay() {
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.3f)))
        val inf = rememberInfiniteTransition(label = "scan-line")
        val progress by inf.animateFloat(0f, 1f, infiniteRepeatable(animation = tween(1100), repeatMode = RepeatMode.Reverse), label = "progress")
        BoxWithConstraints(Modifier.fillMaxSize()) {
            Box(Modifier.fillMaxWidth().height(4.dp).offset(y = maxHeight * progress).background(Brush.horizontalGradient(listOf(Color.Transparent, MaterialTheme.colorScheme.primary, Color.Transparent))))
        }
        Surface(modifier = Modifier.align(Alignment.Center), shape = RoundedCornerShape(22.dp), color = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f)) {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                Text("Scanning and ranking candidates...")
            }
        }
    }
}

@Composable
private fun SettingsDialog(isDark: Boolean, serverMessage: String, serverBaseUrl: String?, loading: Boolean, onRefresh: () -> Unit, onToggleTheme: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
        title = { Text("Settings") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween, Alignment.CenterVertically) { Text("Dark mode"); Switch(checked = isDark, onCheckedChange = { onToggleTheme() }) }
                Text(serverMessage, color = MaterialTheme.colorScheme.onSurfaceVariant)
                serverBaseUrl?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
                FilledTonalButton(onClick = onRefresh, enabled = !loading, modifier = Modifier.fillMaxWidth()) { Text("Find server again") }
            }
        }
    )
}

private fun cameraStatus(status: ServerConnectionStatus): String = when (status) {
    ServerConnectionStatus.CONNECTED -> "Server ready"
    ServerConnectionStatus.SEARCHING -> "Finding server"
    ServerConnectionStatus.OFFLINE -> "Server offline"
}

private fun dietaryLabelIcon(label: String): String = when (label) {
    "Gluten-Free" -> "\uD83C\uDF3E"
    "Lactose-Free" -> "\uD83E\uDD5B"
    "Dairy-Free" -> "\uD83E\uDD65"
    "High-Protein" -> "\uD83D\uDCAA"
    "Low Sugar" -> "\uD83D\uDCC9"
    "Sugar-Free" -> "\u26D4"
    "Vegan" -> "\uD83C\uDF31"
    "Vegetarian" -> "\uD83E\uDD55"
    "Organic" -> "\uD83C\uDF43"
    "Keto-Friendly" -> "\uD83E\uDD51"
    "UHT" -> "\uD83D\uDD25"
    else -> "\uD83C\uDFF7\uFE0F"
}

private fun candidateLabel(candidate: ProductCandidate): String = buildString {
    append(candidate.name)
}

private fun candidateMeasurementLabel(candidate: ProductCandidate): String? = when {
    candidate.volume_l != null -> "${candidate.volume_l} L"
    candidate.weight_g != null -> "${candidate.weight_g.toInt()} g"
    candidate.pieces != null -> "${candidate.pieces} pcs"
    else -> null
}

private fun Context.mainExecutor(): Executor = androidx.core.content.ContextCompat.getMainExecutor(this)

private fun takePhoto(context: Context, imageCapture: ImageCapture, onFile: (File) -> Unit, onError: (String) -> Unit) {
    val file = File(context.cacheDir, "scan_${SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())}.jpg")
    val output = ImageCapture.OutputFileOptions.Builder(file).build()
    imageCapture.takePicture(output, context.mainExecutor(), object : ImageCapture.OnImageSavedCallback {
        override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) { try { BitmapFactory.decodeFile(file.absolutePath) } catch (_: Exception) {}; onFile(file) }
        override fun onError(exception: ImageCaptureException) { Log.e("RootScreen", "Photo capture failed", exception); onError("Photo capture failed. Please try again.") }
    })
}
