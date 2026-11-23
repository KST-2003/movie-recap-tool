# Android release signing

The Play upload key is separate from the debug key. Never commit the keystore or `key.properties`, share their passwords in chat, or replace an existing Play upload key with a new one.

On the release computer, `android/key.properties` contains `storeFile`, `storePassword`, `keyAlias`, and `keyPassword`. The file is Git-ignored. `storeFile` points to the upload keystore outside the repository. Keep secure backups of the keystore and credentials separately; losing them can prevent future updates until the upload key is reset through Google Play.

From `frontend/`, build the native web assets and run `npx cap sync android`. From `frontend/android/`, run `gradlew.bat :app:bundleRelease` on Windows (or `./gradlew :app:bundleRelease` on macOS/Linux) with JDK 21. The signed bundle is `app/build/outputs/bundle/release/app-release.aab`. If `key.properties` is missing, Gradle does not configure a release key; an unsigned artifact is not suitable for Play Console. Verify the signature before upload.

For Play App Signing, Google signs the APKs distributed to users with the app signing key; the local upload key signs the bundle submitted to Play. The Play Console internal-testing track provides a production-like install path.
