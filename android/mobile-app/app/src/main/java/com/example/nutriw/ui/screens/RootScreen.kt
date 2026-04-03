package com.example.nutriw.ui.screens

import android.Manifest
import android.content.Context
import android.graphics.BitmapFactory
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.nutriw.vm.ScanFlow
import com.example.nutriw.vm.ScanViewModel
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executor

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RootScreen(
    isDark: Boolean,
    onToggleTheme: () -> Unit,
    vm: ScanViewModel = viewModel()
) {
    var menuOpen by remember { mutableStateOf(false) }
    var showSettings by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("NutriW") },
                actions = {
                    Box {
                        IconButton(onClick = { menuOpen = true }) {
                            Icon(Icons.Default.MoreVert, contentDescription = "Menu")
                        }
                        DropdownMenu(
                            expanded = menuOpen,
                            onDismissRequest = { menuOpen = false }
                        ) {
                            DropdownMenuItem(
                                text = { Text("Recipes") },
                                onClick = {
                                    menuOpen = false
                                    vm.openRecipes()
                                },
                                enabled = vm.canOpenRecipes
                            )
                            DropdownMenuItem(
                                text = { Text("Settings") },
                                onClick = {
                                    menuOpen = false
                                    showSettings = true
                                }
                            )
                        }
                    }
                }
            )
        }
    ) { pad ->
        Box(
            Modifier
                .fillMaxSize()
                .padding(pad)
        ) {
            AnimatedContent(
                targetState = vm.flow,
                transitionSpec = { fadeIn() togetherWith fadeOut() },
                label = "flow"
            ) { flow ->
                when (flow) {
                    ScanFlow.CAMERA -> CameraScanScreen(vm)
                    ScanFlow.PRODUCTS -> ProductsReviewScreen(vm)
                    ScanFlow.RECIPES -> RecipesScreen(vm)
                }
            }
        }
    }

    if (showSettings) {
        SettingsDialog(
            isDark = isDark,
            onToggleTheme = onToggleTheme,
            onDismiss = { showSettings = false }
        )
    }
}

@Composable
private fun SettingsDialog(
    isDark: Boolean,
    onToggleTheme: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("Close") }
        },
        title = { Text("Settings") },
        text = {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text("Dark mode")
                Switch(checked = isDark, onCheckedChange = { onToggleTheme() })
            }
        }
    )
}

@Composable
private fun CameraScanScreen(vm: ScanViewModel) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    var hasCameraPermission by remember { mutableStateOf(false) }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        hasCameraPermission = granted
    }

    LaunchedEffect(Unit) {
        permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    if (!hasCameraPermission) {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Text("Camera permission is required.", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(12.dp))
            Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }) {
                Text("Grant permission")
            }
        }
        return
    }

    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }

    Box(Modifier.fillMaxSize()) {
        val captured = vm.capturedImageBitmap
        if (captured != null) {
            Image(
                bitmap = captured.asImageBitmap(),
                contentDescription = "Captured",
                modifier = Modifier.fillMaxSize()
            )
        } else {
            AndroidView(
                factory = { ctx ->
                    PreviewView(ctx).also { previewView ->
                        val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
                        cameraProviderFuture.addListener({
                            val cameraProvider = cameraProviderFuture.get()
                            val preview = Preview.Builder().build().also {
                                it.setSurfaceProvider(previewView.surfaceProvider)
                            }
                            val capture = ImageCapture.Builder()
                                .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                                .build()
                            imageCapture = capture
                            try {
                                cameraProvider.unbindAll()
                                cameraProvider.bindToLifecycle(
                                    lifecycleOwner,
                                    CameraSelector.DEFAULT_BACK_CAMERA,
                                    preview,
                                    capture
                                )
                            } catch (e: Exception) {
                                Log.e("CameraScanScreen", "Camera bind failed", e)
                            }
                        }, ctx.mainExecutor())
                    }
                },
                modifier = Modifier.fillMaxSize()
            )
        }

        if (vm.isLoading) {
            ScanningOverlay()
        }

        // Show error (if any) over the camera/static preview
        if (vm.errorMessage != null && !vm.isLoading) {
            Surface(
                tonalElevation = 2.dp,
                shape = RoundedCornerShape(14.dp),
                color = MaterialTheme.colorScheme.errorContainer,
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .padding(16.dp)
            ) {
                Text(
                    text = vm.errorMessage ?: "",
                    color = MaterialTheme.colorScheme.onErrorContainer,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp)
                )
            }
        }

        if (!vm.isLoading) {
            Button(
                onClick = {
                    val cap = imageCapture ?: return@Button
                    takePhoto(context, cap) { file ->
                        // Store static image immediately (VM will also decode again; cheap and fine for MVP)
                        vm.scan(file)
                    }
                },
                shape = RoundedCornerShape(18.dp),
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 24.dp)
                    .height(56.dp)
                    .widthIn(min = 160.dp)
            ) {
                Text("SCAN")
            }
        }
    }
}

@Composable
private fun ScanningOverlay() {
    Box(Modifier.fillMaxSize()) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.25f))
        )

        val infinite = rememberInfiniteTransition(label = "scanLine")
        val progress by infinite.animateFloat(
            initialValue = 0f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                animation = tween(1100),
                repeatMode = RepeatMode.Reverse
            ),
            label = "scanLineProgress"
        )

        BoxWithConstraints(Modifier.fillMaxSize()) {
            val y = maxHeight * progress
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(3.dp)
                    .offset(y = y)
                    .background(MaterialTheme.colorScheme.primary)
            )
        }
    }
}

@Composable
private fun ProductsReviewScreen(vm: ScanViewModel) {
    val products = vm.editableProducts

    Column(
        Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Text("Check products", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(12.dp))

        LazyColumn(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            itemsIndexed(products) { index, p ->
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp)) {
                        OutlinedTextField(
                            value = p.name,
                            onValueChange = { vm.updateProductName(index, it) },
                            label = { Text("Name") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth()
                        )
                        Spacer(Modifier.height(10.dp))
                        OutlinedTextField(
                            value = p.amount,
                            onValueChange = { vm.updateProductAmount(index, it) },
                            label = { Text("Amount") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedButton(
                onClick = { vm.scanAgain() },
                modifier = Modifier.weight(1f)
            ) {
                Text("Scan again")
            }
            Button(
                onClick = { vm.confirmProducts() },
                modifier = Modifier.weight(1f)
            ) {
                Text("Confirm")
            }
        }
    }
}

@Composable
private fun RecipesScreen(vm: ScanViewModel) {
    val recipes = vm.recipes

    Column(
        Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Text("Recipes", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(12.dp))

        if (recipes.isEmpty()) {
            Text("No recipes yet. Confirm products first.")
            return
        }

        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            itemsIndexed(recipes) { _, r ->
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp)) {
                        Text(r.titlePl, style = MaterialTheme.typography.titleMedium)
                        r.kcalPerPortion?.let { Text("kcal/porcja: ${"%.0f".format(it)}") }
                        if (r.missing.isNotEmpty()) {
                            Spacer(Modifier.height(6.dp))
                            Text("Co dokupić:")
                            r.missing.forEach { Text("• $it") }
                        }
                    }
                }
            }
        }
    }
}

private fun Context.mainExecutor(): Executor =
    androidx.core.content.ContextCompat.getMainExecutor(this)

private fun takePhoto(
    context: Context,
    imageCapture: ImageCapture,
    onFile: (File) -> Unit
) {
    val outputDir = context.cacheDir
    val file = File(
        outputDir,
        "scan_${SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())}.jpg"
    )
    val output = ImageCapture.OutputFileOptions.Builder(file).build()

    imageCapture.takePicture(
        output,
        context.mainExecutor(),
        object : ImageCapture.OnImageSavedCallback {
            override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                // quick decode ensures file exists and is readable; VM decodes for UI
                try { BitmapFactory.decodeFile(file.absolutePath) } catch (_: Exception) {}
                onFile(file)
            }

            override fun onError(exception: ImageCaptureException) {
                Log.e("RootScreen", "Photo capture failed", exception)
            }
        }
    )
}
