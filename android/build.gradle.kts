// Versions are pinned deliberately. This project is built by CI, never on the
// author's machine, so a floating version would mean a build that breaks without
// anyone changing a line.
plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}
