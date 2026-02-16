//! FINRA 3110 Audit Logging
//!
//! Append-only audit trail with daily rotation.

use crate::engine::AuditRecord;
use anyhow::Result;
use chrono::{DateTime, Local, Utc};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

// ---------------------------------------------------------------------------
// Audit Logger
// ---------------------------------------------------------------------------

/// FINRA 3110 compliant audit logger
pub struct AuditLogger {
    log_dir: PathBuf,
    current_file: Mutex<Option<File>>,
    current_date: Mutex<String>,
}

impl AuditLogger {
    /// Create a new audit logger
    pub fn new(log_dir: impl AsRef<Path>) -> Result<Self> {
        let log_dir = log_dir.as_ref().to_path_buf();

        // Create log directory if it doesn't exist
        if !log_dir.exists() {
            std::fs::create_dir_all(&log_dir)?;
        }

        Ok(Self {
            log_dir,
            current_file: Mutex::new(None),
            current_date: Mutex::new(String::new()),
        })
    }

    /// Log an audit event
    pub fn log_event(&self, record: &AuditRecord, extra: Option<&str>) -> Result<()> {
        let mut file_guard = self.current_file.lock().unwrap();
        let mut date_guard = self.current_date.lock().unwrap();

        // Check if we need to rotate (new day)
        let current_date = Local::now().format("%Y-%m-%d").to_string();
        if *date_guard != current_date {
            // Flush and close old file
            if let Some(ref mut f) = *file_guard {
                f.flush()?;
            }

            // Open new file
            let file_path = self.log_dir.join(format!("audit_{}.jsonl", current_date));
            let new_file = OpenOptions::new()
                .create(true)
                .append(true)
                .open(&file_path)?;

            *file_guard = Some(new_file);
            *date_guard = current_date.clone();

            log::info!("Audit log rotated to: {:?}", file_path);
        }

        // Ensure file is open
        if file_guard.is_none() {
            let file_path = self.log_dir.join(format!("audit_{}.jsonl", current_date));
            let new_file = OpenOptions::new()
                .create(true)
                .append(true)
                .open(&file_path)?;
            *file_guard = Some(new_file);
            *date_guard = current_date;
        }

        // Format log entry as JSON
        let log_entry = AuditLogEntry {
            timestamp_ns: record.timestamp_ns,
            event_type: format!("{:?}", record.event_type),
            sleeve_id: record.sleeve_id,
            signal_value: record.signal_value,
            position_delta: record.position_delta,
            risk_flag: record.risk_flag,
            extra: extra.map(|s| s.to_string()),
        };

        let json = serde_json::to_string(&log_entry)?;

        // Write to file
        if let Some(ref mut f) = *file_guard {
            writeln!(f, "{}", json)?;
            // Flush for durability (critical for audit trail)
            f.flush()?;
        }

        Ok(())
    }

    /// Flush all buffered data
    pub fn flush(&self) -> Result<()> {
        let mut file_guard = self.current_file.lock().unwrap();
        if let Some(ref mut f) = *file_guard {
            f.flush()?;
        }
        Ok(())
    }

    /// Get the current log file path
    pub fn current_log_path(&self) -> PathBuf {
        let date_guard = self.current_date.lock().unwrap();
        if date_guard.is_empty() {
            let current_date = Local::now().format("%Y-%m-%d").to_string();
            self.log_dir.join(format!("audit_{}.jsonl", current_date))
        } else {
            self.log_dir.join(format!("audit_{}.jsonl", *date_guard))
        }
    }

    /// Get audit log files in date range
    pub fn get_logs_in_range(
        &self,
        start_date: DateTime<Utc>,
        end_date: DateTime<Utc>,
    ) -> Result<Vec<PathBuf>> {
        let mut logs = Vec::new();

        let entries = std::fs::read_dir(&self.log_dir)?;
        for entry in entries {
            let entry = entry?;
            let path = entry.path();

            if path.extension().and_then(|s| s.to_str()) == Some("jsonl") {
                if let Some(filename) = path.file_name().and_then(|s| s.to_str()) {
                    // Extract date from filename: audit_YYYY-MM-DD.jsonl
                    if filename.starts_with("audit_") && filename.ends_with(".jsonl") {
                        let date_str = &filename[6..filename.len() - 6]; // Remove "audit_" and ".jsonl"
                        if let Ok(file_date) =
                            chrono::NaiveDate::parse_from_str(date_str, "%Y-%m-%d")
                        {
                            // Use and_hms_opt with proper error handling
                            if let Some(naive_dt) = file_date.and_hms_opt(0, 0, 0) {
                                let file_datetime = naive_dt.and_utc();
                                if file_datetime >= start_date && file_datetime <= end_date {
                                    logs.push(path);
                                }
                            }
                        }
                    }
                }
            }
        }

        logs.sort();
        Ok(logs)
    }
}

// ---------------------------------------------------------------------------
// Audit Log Entry (JSON serialization)
// ---------------------------------------------------------------------------

#[derive(Debug, serde::Serialize, serde::Deserialize)]
struct AuditLogEntry {
    timestamp_ns: u64,
    event_type: String,
    sleeve_id: u8,
    signal_value: f64,
    position_delta: f64,
    risk_flag: u8,
    extra: Option<String>,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::{now_ns, AuditEventType};
    use tempfile::TempDir;

    #[test]
    fn test_audit_logger_creation() {
        let temp_dir = TempDir::new().unwrap();
        let logger = AuditLogger::new(temp_dir.path());
        assert!(logger.is_ok());
    }

    #[test]
    fn test_log_event() {
        let temp_dir = TempDir::new().unwrap();
        let logger = AuditLogger::new(temp_dir.path()).unwrap();

        let record = AuditRecord {
            timestamp_ns: now_ns(),
            event_type: AuditEventType::SleeveSignal,
            sleeve_id: 1,
            signal_value: 0.5,
            position_delta: 100.0,
            risk_flag: 0,
        };

        let result = logger.log_event(&record, Some("test event"));
        assert!(result.is_ok());

        // Verify file was created
        let log_path = logger.current_log_path();
        assert!(log_path.exists());
    }

    #[test]
    fn test_log_multiple_events() {
        let temp_dir = TempDir::new().unwrap();
        let logger = AuditLogger::new(temp_dir.path()).unwrap();

        for i in 0..10 {
            let record = AuditRecord {
                timestamp_ns: now_ns(),
                event_type: AuditEventType::SleeveSignal,
                sleeve_id: i,
                signal_value: i as f64 * 0.1,
                position_delta: i as f64 * 10.0,
                risk_flag: 0,
            };

            logger.log_event(&record, None).unwrap();
        }

        logger.flush().unwrap();

        // Verify all events were written
        let log_path = logger.current_log_path();
        let content = std::fs::read_to_string(log_path).unwrap();
        let line_count = content.lines().count();
        assert_eq!(line_count, 10);
    }

    #[test]
    fn test_log_entry_json_format() {
        let entry = AuditLogEntry {
            timestamp_ns: 1234567890,
            event_type: "SleeveSignal".to_string(),
            sleeve_id: 1,
            signal_value: 0.75,
            position_delta: 150.0,
            risk_flag: 0,
            extra: Some("test data".to_string()),
        };

        let json = serde_json::to_string(&entry).unwrap();
        assert!(json.contains("timestamp_ns"));
        assert!(json.contains("SleeveSignal"));
        assert!(json.contains("test data"));

        // Should be deserializable
        let parsed: AuditLogEntry = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.timestamp_ns, 1234567890);
        assert_eq!(parsed.sleeve_id, 1);
    }

    #[test]
    fn test_flush() {
        let temp_dir = TempDir::new().unwrap();
        let logger = AuditLogger::new(temp_dir.path()).unwrap();

        let record = AuditRecord {
            timestamp_ns: now_ns(),
            event_type: AuditEventType::Heartbeat,
            sleeve_id: 0,
            signal_value: 0.0,
            position_delta: 0.0,
            risk_flag: 0,
        };

        logger.log_event(&record, None).unwrap();
        let result = logger.flush();
        assert!(result.is_ok());
    }
}
