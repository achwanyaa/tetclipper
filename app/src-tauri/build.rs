fn main() {
    // The update check's release repo is compiled in (src/update.rs).
    println!("cargo:rerun-if-env-changed=TETCLIPPER_RELEASES_REPO");
    tauri_build::build()
}
