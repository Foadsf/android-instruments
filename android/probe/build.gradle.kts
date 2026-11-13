plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "io.github.foadsf.instruments.probe"
    compileSdk {
        version = release(37) { minorApiLevel = 0 }
    }
    buildToolsVersion = "37.0.0"

    defaultConfig {
        applicationId = "io.github.foadsf.instruments.probe"
        // API 29: SessionConfiguration, isSessionConfigurationSupported, physical camera streams.
        minSdk = 29
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    // No Google-encrypted dependency blob in the APK.
    dependenciesInfo {
        includeInApk = false
        includeInBundle = false
    }
}

dependencies {
    testImplementation(libs.junit)
}
