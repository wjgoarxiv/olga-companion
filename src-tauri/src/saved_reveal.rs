//! Paths the sidecar recorded after a native save. The webview sends an id, never a path.

use std::fs;
use std::path::{Path, PathBuf};

const ID_LEN: usize = 32;

pub fn path_for_reveal(app_data: &Path, reveal_id: &str) -> Option<PathBuf> {
    if !is_reveal_id(reveal_id) {
        return None;
    }
    let text = fs::read_to_string(app_data.join("var").join("saved-reveals.json")).ok()?;
    let value: serde_json::Value = serde_json::from_str(&text).ok()?;
    let stored = value.get(reveal_id)?.as_str()?;
    if stored.chars().any(|ch| matches!(ch, '\0' | '\n' | '\r')) {
        return None;
    }
    let candidate = Path::new(stored);
    if !candidate.is_absolute() {
        return None;
    }
    let resolved = candidate.canonicalize().ok()?;
    if !resolved.is_file() {
        return None;
    }
    Some(resolved)
}

fn is_reveal_id(value: &str) -> bool {
    value.len() == ID_LEN
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

/// Open Explorer with this file selected. The caller has already checked the allow-list.
/// `explorer.exe` is started directly, not through a shell and not through the shell plugin.
#[cfg(target_os = "windows")]
pub fn reveal_in_explorer(path: &Path) -> Result<(), &'static str> {
    let mut select = std::ffi::OsString::from(r"/select,");
    select.push(path);
    match std::process::Command::new("explorer.exe").arg(select).spawn() {
        Ok(_child) => Ok(()),
        Err(_) => Err("reveal_unavailable"),
    }
}

#[cfg(not(target_os = "windows"))]
pub fn reveal_in_explorer(path: &Path) -> Result<(), &'static str> {
    let _ = path;
    Err("reveal_unavailable")
}

#[cfg(test)]
#[allow(clippy::expect_used, clippy::unwrap_used)]
mod tests {
    use super::*;

    fn scratch() -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "olga-reveal-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        fs::create_dir_all(root.join("var")).expect("scratch");
        root
    }

    #[test]
    fn an_unlisted_id_or_raw_path_is_refused() {
        let root = scratch();
        let listed = root.join("listed.md");
        fs::write(&listed, b"report").expect("file");
        let id = "ab".repeat(16);
        let mut body = serde_json::Map::new();
        body.insert(
            id.clone(),
            serde_json::Value::String(listed.display().to_string()),
        );
        fs::write(
            root.join("var").join("saved-reveals.json"),
            serde_json::Value::Object(body).to_string(),
        )
        .expect("allow-list");

        assert!(path_for_reveal(&root, &id).is_some());
        assert!(path_for_reveal(&root, &"cd".repeat(16)).is_none());
        assert!(path_for_reveal(&root, &listed.display().to_string()).is_none());
        let _ = fs::remove_dir_all(root);
    }
}
