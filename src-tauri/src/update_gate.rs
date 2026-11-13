//! Installing an update stops the local backend, and with it any run it supervises. The
//! backend decides whether that is safe (it alone knows what is starting or running), and
//! this side refuses to stop it unless the answer is a confirmed yes. A page that merely
//! disables its button is not a defence: the check happens here, in the native command.

use std::io::{ErrorKind, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::{Value, json};

/// How long the backend may take to scan its run receipts before the answer counts as
/// "could not confirm".
pub const GATE_TIMEOUT: Duration = Duration::from_secs(20);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
/// The token endpoint does no work; a backend that cannot answer it in this time is stalled.
const TOKEN_TIMEOUT: Duration = Duration::from_secs(5);
const RELEASE_TIMEOUT: Duration = Duration::from_secs(3);
/// Far above any real answer; the backend replies with a few hundred bytes.
const MAX_RESPONSE_BYTES: usize = 64 * 1024;
const MAX_TOKEN_LEN: usize = 256;

/// What the webview receives when a stop is refused: a stable `code` to branch on and a
/// `message` that is safe to show as written.
pub fn refusal(code: &str, message: &str) -> Value {
    json!({ "code": code, "message": message })
}

fn http(port: &str, request: &str, timeout: Duration) -> Result<(u16, String), std::io::Error> {
    let port: u16 = port
        .parse()
        .map_err(|_| std::io::Error::new(ErrorKind::InvalidInput, "port"))?;
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let deadline = Instant::now() + timeout;
    let mut stream = TcpStream::connect_timeout(&address, CONNECT_TIMEOUT.min(timeout))?;
    stream.set_write_timeout(Some(timeout))?;
    stream.write_all(request.as_bytes())?;
    // One overall deadline and a byte cap: a peer that drips bytes or never stops sending
    // must not hold the update (or memory) hostage.
    let mut raw = Vec::new();
    let mut chunk = [0_u8; 4096];
    loop {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .filter(|left| !left.is_zero())
            .ok_or_else(|| std::io::Error::new(ErrorKind::TimedOut, "deadline"))?;
        stream.set_read_timeout(Some(remaining))?;
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(count) => {
                raw.extend_from_slice(&chunk[..count]);
                if raw.len() > MAX_RESPONSE_BYTES {
                    return Err(std::io::Error::new(
                        ErrorKind::InvalidData,
                        "response too large",
                    ));
                }
            }
            Err(error) if error.kind() == ErrorKind::Interrupted => {}
            Err(error) => return Err(error),
        }
    }
    let text = String::from_utf8_lossy(&raw).into_owned();
    let invalid = || std::io::Error::new(ErrorKind::InvalidData, "unexpected response");
    let (head, body) = text.split_once("\r\n\r\n").ok_or_else(invalid)?;
    if head
        .to_ascii_lowercase()
        .contains("transfer-encoding: chunked")
    {
        return Err(invalid());
    }
    let status = head
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|code| code.parse::<u16>().ok())
        .ok_or_else(invalid)?;
    Ok((status, body.to_owned()))
}

/// The boot token is URL-safe base64; anything else would be header injection.
fn is_plain_token(token: &str) -> bool {
    (1..=MAX_TOKEN_LEN).contains(&token.len())
        && token
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}

/// Names this stop attempt to the backend, so only the attempt that closed launching can
/// reopen it. Unique per attempt; never derived from anything the backend sends.
pub fn new_prepare_id() -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_nanos());
    format!(
        "{:x}-{nanos:x}-{:x}",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::Relaxed)
    )
}

fn request(
    method: &str,
    path: &str,
    port: &str,
    token: Option<&str>,
    prepare_id: Option<&str>,
) -> String {
    let token_header =
        token.map_or_else(String::new, |value| format!("X-Session-Token: {value}\r\n"));
    let id_header = prepare_id.map_or_else(String::new, |value| {
        format!("X-Update-Prepare-Id: {value}\r\n")
    });
    format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{token_header}{id_header}Content-Length: 0\r\nConnection: close\r\n\r\n"
    )
}

fn unconfirmed() -> Value {
    refusal(
        "unconfirmed",
        "Could not confirm that no run is active, so the update was not installed. Open Run to check on your runs, then try again.",
    )
}

/// Windows reports a closed loopback port as a timeout rather than a refusal, so "nobody
/// is listening" is established by being able to take the port ourselves.
fn nothing_is_listening(port: &str) -> bool {
    TcpListener::bind(format!("127.0.0.1:{port}")).is_ok()
}

enum Token {
    Got(String),
    NobodyListening,
    Unconfirmed,
}

fn fetch_token(port: &str, timeout: Duration) -> Token {
    match http(
        port,
        &request("GET", "/api/session/token", port, None, None),
        timeout.min(TOKEN_TIMEOUT),
    ) {
        Ok((200, body)) => serde_json::from_str::<Value>(&body)
            .ok()
            .and_then(|value| {
                value
                    .get("token")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            })
            .filter(|token| is_plain_token(token))
            .map_or(Token::Unconfirmed, Token::Got),
        Err(_) if nothing_is_listening(port) => Token::NobodyListening,
        Ok(_) | Err(_) => Token::Unconfirmed,
    }
}

fn prepare(port: &str, timeout: Duration, prepare_id: &str, token: &str) -> Result<(), Value> {
    let (status, body) = http(
        port,
        &request(
            "POST",
            "/api/update/prepare",
            port,
            Some(token),
            Some(prepare_id),
        ),
        timeout,
    )
    .map_err(|_| unconfirmed())?;
    if status != 200 {
        return Err(unconfirmed());
    }
    let answer: Value = serde_json::from_str(&body).map_err(|_| unconfirmed())?;
    let flag = |name: &str| answer.get(name).and_then(Value::as_bool);
    let blocking_empty = answer
        .get("blocking")
        .and_then(Value::as_array)
        .is_some_and(Vec::is_empty);
    let starting_zero = answer.get("starting").and_then(Value::as_u64) == Some(0);
    match (flag("safe"), flag("confirmed")) {
        (Some(true), Some(true)) if blocking_empty && starting_zero => Ok(()),
        (Some(false), Some(true)) => {
            let message = answer
                .get("message")
                .and_then(Value::as_str)
                .filter(|text| !text.is_empty())
                .unwrap_or("A run is still active, so the update was not installed.");
            Err(refusal("run_active", message))
        }
        _ => Err(unconfirmed()),
    }
}

/// Best effort, for when this side will not stop the backend after all (it gave up waiting,
/// or the stop did not take): reopen launching, but only if this attempt closed it.
pub fn release_prepare(port: &str, prepare_id: &str, timeout: Duration) {
    let wait = timeout.min(RELEASE_TIMEOUT);
    if let Token::Got(token) = fetch_token(port, wait) {
        let _ = http(
            port,
            &request(
                "POST",
                "/api/update/release",
                port,
                Some(&token),
                Some(prepare_id),
            ),
            wait,
        );
    }
}

/// `Ok` only when the backend positively answered `safe` and `confirmed` with nothing
/// starting or blocking, or when nothing is listening at all (then there is nothing to
/// interrupt). Anything else, including silence, a bad status, an oversized or unreadable
/// answer or a contradictory one, refuses. A positive answer closes launching on the
/// backend until it is stopped; any failure after the request was sent releases it again.
pub fn authorize_stop(port: &str, timeout: Duration, prepare_id: &str) -> Result<(), Value> {
    let token = match fetch_token(port, timeout) {
        Token::Got(token) => token,
        Token::NobodyListening => return Ok(()),
        Token::Unconfirmed => return Err(unconfirmed()),
    };
    let result = prepare(port, timeout, prepare_id, &token);
    // A confirmed "run active" left nothing closed; any other failure may have (the answer
    // can be lost on its way back).
    let confirmed_refusal = result
        .as_ref()
        .err()
        .is_some_and(|value| value["code"] == "run_active");
    if result.is_err() && !confirmed_refusal {
        release_prepare(port, prepare_id, timeout);
    }
    result
}

#[cfg(test)]
#[allow(clippy::expect_used, clippy::unwrap_used)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex};
    use std::thread::JoinHandle;

    const SHORT: Duration = Duration::from_millis(400);

    fn reply(status: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    /// Answers one connection per canned reply (`None` = accept and stay silent) and
    /// records each request it saw.
    fn backend(replies: Vec<Option<String>>) -> (String, Arc<Mutex<Vec<String>>>, JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fake backend");
        let port = listener
            .local_addr()
            .expect("fake backend address")
            .port()
            .to_string();
        let seen = Arc::new(Mutex::new(Vec::new()));
        let log = Arc::clone(&seen);
        let handle = std::thread::spawn(move || {
            // One thread per connection, numbered in accept order, so a silent connection
            // does not stop the next one from being answered.
            let mut workers = Vec::new();
            for canned in replies {
                let Ok((mut stream, _)) = listener.accept() else {
                    return;
                };
                let log = Arc::clone(&log);
                workers.push(std::thread::spawn(move || {
                    let mut buffer = [0_u8; 4096];
                    let mut request = String::new();
                    while !request.contains("\r\n\r\n") {
                        match stream.read(&mut buffer) {
                            Ok(0) | Err(_) => break,
                            Ok(count) => {
                                request.push_str(&String::from_utf8_lossy(&buffer[..count]));
                            }
                        }
                    }
                    if let Ok(mut guard) = log.lock() {
                        guard.push(request);
                    }
                    match canned {
                        Some(text) => {
                            let _ = stream.write_all(text.as_bytes());
                        }
                        None => std::thread::sleep(SHORT * 3),
                    }
                }));
            }
            // A real backend stays bound; so does this one while the test inspects the result.
            std::thread::sleep(Duration::from_secs(2));
            drop(workers);
        });
        (port, seen, handle)
    }

    fn token_reply() -> String {
        reply("200 OK", r#"{"token":"boot-token"}"#)
    }

    fn code(result: &Result<(), Value>) -> Option<&str> {
        result
            .as_ref()
            .err()
            .and_then(|value| value["code"].as_str())
    }

    #[test]
    fn an_idle_backend_authorizes_the_stop_with_its_own_token() {
        let (port, seen, handle) = backend(vec![
            Some(token_reply()),
            Some(reply(
                "200 OK",
                r#"{"safe":true,"confirmed":true,"blocking":[],"starting":0,"message":""}"#,
            )),
        ]);

        assert!(authorize_stop(&port, SHORT, "test-id").is_ok());
        drop(handle);

        let requests = seen.lock().expect("requests").clone();
        assert!(requests[1].starts_with("POST /api/update/prepare HTTP/1.1"));
        assert!(requests[1].contains("X-Session-Token: boot-token"));
        assert!(requests[1].contains(&format!("Host: 127.0.0.1:{port}")));
    }

    #[test]
    fn the_prepare_and_the_release_carry_the_same_attempt_id() {
        let released = r#"{"released":true}"#;
        let (port, seen, handle) = backend(vec![
            Some(token_reply()),
            // The positive answer is lost on its way back (here: it never arrives).
            None,
            Some(token_reply()),
            Some(reply("200 OK", released)),
        ]);

        let result = authorize_stop(&port, SHORT, "attempt-7");
        std::thread::sleep(Duration::from_millis(300));
        drop(handle);

        assert_eq!(code(&result), Some("unconfirmed"));
        let requests = seen.lock().expect("requests").clone();
        assert!(requests[1].starts_with("POST /api/update/prepare"));
        assert!(requests[1].contains("X-Update-Prepare-Id: attempt-7"));
        let release = requests
            .iter()
            .find(|text| text.starts_with("POST /api/update/release"))
            .expect("a lost answer must be followed by a release");
        assert!(release.contains("X-Update-Prepare-Id: attempt-7"));
        assert!(release.contains("X-Session-Token: boot-token"));
    }

    #[test]
    fn a_confirmed_refusal_sends_no_release_because_nothing_was_closed() {
        let (port, seen, handle) = backend(vec![
            Some(token_reply()),
            Some(reply(
                "200 OK",
                r#"{"safe":false,"confirmed":true,"blocking":[{"run_id":"r1","state":"running"}],"starting":0,"message":"busy"}"#,
            )),
        ]);

        let result = authorize_stop(&port, SHORT, "attempt-8");
        std::thread::sleep(Duration::from_millis(200));
        drop(handle);

        assert_eq!(code(&result), Some("run_active"));
        assert!(
            seen.lock()
                .expect("requests")
                .iter()
                .all(|text| !text.contains("/api/update/release"))
        );
    }

    #[test]
    fn attempt_ids_are_unique_and_header_safe() {
        let ids: Vec<String> = (0..50).map(|_| new_prepare_id()).collect();
        let mut sorted = ids.clone();
        sorted.sort();
        sorted.dedup();
        assert_eq!(sorted.len(), ids.len());
        assert!(ids.iter().all(|id| {
            (1..=64).contains(&id.len())
                && id
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
        }));
    }

    #[test]
    fn an_active_run_refuses_with_the_backends_own_reason() {
        let (port, _seen, handle) = backend(vec![
            Some(token_reply()),
            Some(reply(
                "200 OK",
                r#"{"safe":false,"confirmed":true,"blocking":[{"run_id":"r1","state":"running"}],"starting":0,"message":"run r1 is running"}"#,
            )),
        ]);

        let result = authorize_stop(&port, SHORT, "test-id");
        drop(handle);

        assert_eq!(code(&result), Some("run_active"));
        assert_eq!(result.unwrap_err()["message"], "run r1 is running");
    }

    #[test]
    fn a_backend_that_could_not_look_is_unconfirmed_not_idle() {
        let (port, _seen, handle) = backend(vec![
            Some(token_reply()),
            Some(reply(
                "200 OK",
                r#"{"safe":false,"confirmed":false,"blocking":[],"starting":0,"message":"Could not confirm"}"#,
            )),
        ]);

        let result = authorize_stop(&port, SHORT, "test-id");
        drop(handle);

        assert_eq!(code(&result), Some("unconfirmed"));
    }

    #[test]
    fn silence_a_bad_status_or_garbage_all_refuse() {
        let cases: Vec<Vec<Option<String>>> = vec![
            vec![None],
            vec![Some(token_reply()), None],
            vec![Some(reply("500 Internal Server Error", "{}"))],
            vec![
                Some(token_reply()),
                Some(reply("401 Unauthorized", r#"{"detail":"no"}"#)),
            ],
            vec![Some(token_reply()), Some(reply("200 OK", "not json"))],
            vec![
                Some(token_reply()),
                Some(reply("200 OK", r#"{"unrelated":true}"#)),
            ],
            vec![Some(reply("200 OK", r#"{"token":7}"#))],
            vec![Some(
                "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n".to_owned(),
            )],
        ];
        for replies in cases {
            let (port, _seen, handle) = backend(replies);
            let result = authorize_stop(&port, SHORT, "test-id");
            drop(handle);
            assert_eq!(code(&result), Some("unconfirmed"), "{result:?}");
        }
    }

    #[test]
    fn a_stalled_backend_is_given_up_on_at_the_token_step_not_the_full_gate_timeout() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("address").port().to_string();
        // Accepts and then says nothing for longer than the test allows, like a frozen process.
        let handle = std::thread::spawn(move || {
            let Ok((_stream, _)) = listener.accept() else {
                return;
            };
            std::thread::sleep(Duration::from_secs(12));
        });
        let started = Instant::now();

        let result = authorize_stop(&port, Duration::from_secs(30), "test-id");

        assert_eq!(code(&result), Some("unconfirmed"));
        assert!(
            started.elapsed() < Duration::from_secs(8),
            "{:?}",
            started.elapsed()
        );
        drop(handle);
    }

    #[test]
    fn only_a_complete_positive_answer_authorizes() {
        let contradictory = [
            r#"{"safe":true,"confirmed":false,"blocking":[],"starting":0,"message":""}"#,
            r#"{"safe":true,"blocking":[],"starting":0}"#,
            r#"{"safe":true,"confirmed":"yes","blocking":[],"starting":0}"#,
            r#"{"safe":"true","confirmed":true,"blocking":[],"starting":0}"#,
            r#"{"safe":true,"confirmed":true,"blocking":[{"run_id":"r1","state":"running"}],"starting":0}"#,
            r#"{"safe":true,"confirmed":true,"blocking":[],"starting":1}"#,
            r#"{"safe":true,"confirmed":true,"blocking":[]}"#,
            r#"{"safe":true,"confirmed":true,"starting":0}"#,
            r#"{"safe":false,"confirmed":false,"blocking":[],"starting":0}"#,
            r#"{"safe":false,"blocking":[],"starting":0}"#,
        ];
        for body in contradictory {
            let (port, _seen, handle) =
                backend(vec![Some(token_reply()), Some(reply("200 OK", body))]);
            let result = authorize_stop(&port, SHORT, "test-id");
            drop(handle);
            assert_eq!(code(&result), Some("unconfirmed"), "{body}");
        }
    }

    #[test]
    fn an_unsafe_token_is_never_put_in_a_header() {
        let long = "a".repeat(MAX_TOKEN_LEN + 1);
        let tokens = [
            "",
            "bad\\r\\nX-Injected: 1",
            "has space",
            "semi;colon",
            long.as_str(),
        ];
        for token in tokens {
            let body = format!(r#"{{"token":"{token}"}}"#);
            let (port, seen, handle) = backend(vec![Some(reply("200 OK", &body))]);
            let result = authorize_stop(&port, SHORT, "test-id");
            drop(handle);
            assert_eq!(code(&result), Some("unconfirmed"), "{token:?}");
            assert_eq!(
                seen.lock().expect("requests").len(),
                1,
                "no second request for {token:?}"
            );
        }
    }

    #[test]
    fn an_oversized_answer_is_refused() {
        let filler = "x".repeat(MAX_RESPONSE_BYTES + 10);
        let body = format!(r#"{{"token":"t","pad":"{filler}"}}"#);
        let (port, _seen, handle) = backend(vec![Some(reply("200 OK", &body))]);

        let result = authorize_stop(&port, Duration::from_secs(5), "test-id");
        drop(handle);

        assert_eq!(code(&result), Some("unconfirmed"));
    }

    #[test]
    fn a_slow_drip_answer_hits_the_overall_deadline() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("address").port().to_string();
        let handle = std::thread::spawn(move || {
            let Ok((mut stream, _)) = listener.accept() else {
                return;
            };
            let mut buffer = [0_u8; 2048];
            let _ = stream.read(&mut buffer);
            let _ = stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 400\r\n\r\n");
            // Each byte arrives well inside the per-read timeout, but the sum does not.
            for _ in 0..40 {
                if stream.write_all(b"x").is_err() {
                    return;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        });
        let started = Instant::now();

        let result = authorize_stop(&port, Duration::from_millis(500), "test-id");

        assert_eq!(code(&result), Some("unconfirmed"));
        assert!(
            started.elapsed() < Duration::from_millis(1500),
            "{:?}",
            started.elapsed()
        );
        drop(handle);
    }

    /// Drives the real Python sidecar (started by the caller on an ephemeral port) through
    /// the same HTTP exchange the app uses: `OLGA_GATE_PROBE_PORT` names it and
    /// `OLGA_GATE_PROBE_EXPECT` is `ok`, `run_active` or `unconfirmed`.
    #[test]
    #[ignore = "needs a real sidecar; see OLGA_GATE_PROBE_PORT"]
    fn real_sidecar_gate_probe() {
        let port = std::env::var("OLGA_GATE_PROBE_PORT").expect("OLGA_GATE_PROBE_PORT");
        let expect = std::env::var("OLGA_GATE_PROBE_EXPECT").expect("OLGA_GATE_PROBE_EXPECT");

        let result = authorize_stop(&port, GATE_TIMEOUT, "probe-id");

        println!("PROBE {result:?}");
        match expect.as_str() {
            "ok" => assert!(result.is_ok(), "{result:?}"),
            other => assert_eq!(code(&result), Some(other), "{result:?}"),
        }
    }

    #[test]
    fn nothing_listening_means_there_is_nothing_to_interrupt() {
        let port = {
            let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
            listener.local_addr().expect("address").port().to_string()
        };

        assert!(authorize_stop(&port, SHORT, "test-id").is_ok());
    }
}
