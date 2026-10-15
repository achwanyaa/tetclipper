// secrets.json (API keys, chmod 600) and the one HTTP helper this shell uses
// (the system curl, as check_ollama does).

use std::fs;
use std::io::Write;
use std::path::Path;
use std::process::Stdio;

use serde_json::{json, Value};

use crate::{home_dir, quiet_command};

fn secrets_path() -> std::path::PathBuf {
    home_dir().join("secrets.json")
}

fn read_json(path: &Path) -> Value {
    fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .filter(|v| v.is_object())
        .unwrap_or_else(|| json!({}))
}

pub(crate) fn read_secrets() -> Value {
    read_json(&secrets_path())
}

/// Write the whole secrets object and chmod 600 — the one write path every
/// key goes through.
pub(crate) fn write_secrets_at(path: &Path, current: &Value) -> Result<(), String> {
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    fs::write(path, serde_json::to_string_pretty(current).unwrap()).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

/// Merge one top-level field into secrets.json, keeping every other key.
pub(crate) fn merge_secret(field: &str, value: Value) -> Result<(), String> {
    let mut current = read_secrets();
    current[field] = value;
    write_secrets_at(&secrets_path(), &current)
}

/// One HTTP call through the system curl. A JSON body goes on stdin and a
/// bearer key rides a curl config read from stdin — never argv, which is
/// world-readable in `ps`. The status code arrives on the trailing line.
pub(crate) fn curl_request(
    method: &str,
    url: &str,
    bearer: Option<&str>,
    body: Option<&Value>,
    timeout_secs: u32,
) -> Result<(u16, Value), String> {
    let timeout = timeout_secs.to_string();
    let mut cmd = quiet_command("curl");
    cmd.args([
        "-sS", "-m", &timeout, "-X", method, url,
        "-H", "accept: application/json",
        "-w", "\n%{http_code}",
    ]);
    if body.is_some() {
        cmd.args(["-H", "content-type: application/json"]);
    }
    let stdin_payload = match (bearer, body) {
        (Some(key), Some(body)) => {
            cmd.args(["-K", "-", "--data-binary", &body.to_string()]);
            format!("header = \"authorization: Bearer {key}\"\n")
        }
        (Some(key), None) => {
            cmd.args(["-K", "-"]);
            format!("header = \"authorization: Bearer {key}\"\n")
        }
        (None, Some(body)) => {
            cmd.args(["--data-binary", "@-"]);
            body.to_string()
        }
        (None, None) => String::new(),
    };
    let mut child = cmd
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("curl: {e}"))?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin.write_all(stdin_payload.as_bytes()).map_err(|e| e.to_string())?;
    }
    let out = child.wait_with_output().map_err(|e| e.to_string())?;
    parse_curl_output(&String::from_utf8_lossy(&out.stdout))
}

fn parse_curl_output(text: &str) -> Result<(u16, Value), String> {
    let (payload, code) = text.rsplit_once('\n').unwrap_or(("", text));
    let code: u16 = code.trim().parse().unwrap_or(0);
    if code == 0 {
        return Err("unreachable right now — check your connection".into());
    }
    Ok((code, serde_json::from_str(payload).unwrap_or_else(|_| json!({}))))
}

#[cfg(test)]
mod tests {
    use super::parse_curl_output;

    #[test]
    fn status_code_rides_the_last_line() {
        let (code, body) = parse_curl_output("{\"ok\":true}\n200").unwrap();
        assert_eq!(code, 200);
        assert_eq!(body["ok"], true);
    }

    #[test]
    fn no_status_code_means_unreachable() {
        assert!(parse_curl_output("").is_err());
    }
}
