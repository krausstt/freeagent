plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.krausstt.freeagent"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.krausstt.freeagent"
        minSdk = 26          // WebView.evaluateJavascript and modern TLS
        targetSdk = 35
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = System.getenv("APP_VERSION") ?: "0.1.0"
    }

    // Signed only when CI has decrypted the keystore. Without it the release
    // task is skipped rather than silently producing an APK that can never be
    // updated in place, because Android refuses updates across signing keys.
    //
    // PKCS12 rather than the deprecated JKS, and declared explicitly: letting
    // the plugin infer the store type from the file extension fails on a
    // keystore CI writes as ".jks" while keytool actually wrote PKCS12.
    val storeFilePath = System.getenv("KEYSTORE_PATH")
    signingConfigs {
        if (storeFilePath != null) {
            create("release") {
                storeFile = file(storeFilePath)
                storeType = "PKCS12"
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS") ?: "freeagent"
                keyPassword = System.getenv("KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (storeFilePath != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

// No third-party dependencies on purpose. Every library is a version that can
// fail to resolve in CI, and this app needs none of them: a plain Activity, a
// WebView, and HttpURLConnection cover the whole surface.
dependencies { }
