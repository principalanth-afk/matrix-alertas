plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.matrix.alertas"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.matrix.alertas"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "1.1"
    }

    signingConfigs {
        // Clave FIJA, guardada en el repositorio. Antes cada compilación en
        // GitHub usaba una clave de depuración distinta, y Android se niega a
        // instalar encima una app firmada con otra clave: había que
        // desinstalar y volver a pegar el canal y dar los permisos. Con esta
        // clave, las actualizaciones se instalan encima y no se pierde nada.
        //
        // No es un secreto que proteja nada: solo sirve para que Android
        // reconozca que las versiones son de la misma app.
        create("matrix") {
            storeFile = rootProject.file("matrix.keystore")
            storePassword = "matrixalertas"
            keyAlias = "matrix"
            keyPassword = "matrixalertas"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("matrix")
        }
        debug {
            signingConfig = signingConfigs.getByName("matrix")
        }
    }

    // Avisos de estilo que no deben tumbar la compilación en GitHub.
    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
