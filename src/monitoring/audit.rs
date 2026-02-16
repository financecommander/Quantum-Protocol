//! FINRA 3110 Audit Trail
//!
//! Daily-rotated JSON Lines format with 7-year retention support.

use crate::engine::common::{AuditEventType, AuditRecord};
use serde::Serialize;
use std::fs;
use std::io::Write;
use std::path::PathBuf;

// ---------------------------------------------------------------------------
// Audit Log Entry (JSON serializable)
// ---------------------------------------------------------------------------

#[derive(Serialize, Debug)]
pub struct AuditLogEntry {
    pub timestamp_ns: u64,
    pub event_type: String,
    pub sleeve_id: u8,
    pub signal_value: f64,
    pub position_delta: f64,
    pub risk_flag: u8,
    pub date: String,
}

impl AuditLogEntry {
    pub fn from_record(record: &AuditRecord) -> Self {
        let event_type = match record.event_type {
            AuditEventType::SleeveSignal => "sleeve_signal",
            AuditEventType::CrisisProtocol => "crisis_protocol",
            AuditEventType::ConfigUpdate => "config_update",
            AuditEventType::Heartbeat => "heartbeat",
            AuditEventType::CircuitBreaker => "circuit_breaker",
        }
        .to_string();

        let secs = record.timestamp_ns / 1_000_000_000;
        let days = secs / 86400;
        let date = format!("{}", days); // Simplified date

        Self {
            timestamp_ns: record.timestamp_ns,
            event_type,
            sleeve_id: record.sleeve_id,
            signal_value: record.signal_value,
            position_delta: record.position_delta,
            risk_flag: record.risk_flag,
            date,
        }
    }
}

// ---------------------------------------------------------------------------
// Audit Logger
// ---------------------------------------------------------------------------

pub struct AuditLogger {
    pub log_dir: PathBuf,
    pub retention_days: u32,
    pub current_date: String,
    pub entries_written: u64,
}

impl AuditLogger {
    pub fn new(log_dir: &str, retention_days: u32) -> Self {
        Self {
            log_dir: PathBuf::from(log_dir),
            retention_days,
            current_date: String::new(),
            entries_written: 0,
        }
    }

    /// Get the log file path for a given date string.
    pub fn log_file_path(&self, date: &str) -> PathBuf {
        self.log_dir.join(format!("audit_{}.jsonl", date))
    }

    /// Write an audit record to the log file.
    pub fn write_record(&mut self, record: &AuditRecord) -> Result<(), String> {
        let entry = AuditLogEntry::from_record(record);

        // Check for date rotation
        if entry.date != self.current_date {
            self.current_date = entry.date.clone();
        }

        let path = self.log_file_path(&self.current_date);

        // Ensure directory exists
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| format!("create audit dir: {e}"))?;
        }

        let json = serde_json::to_string(&entry).map_err(|e| format!("serialize audit: {e}"))?;

        let mut file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .map_err(|e| format!("open audit log: {e}"))?;

        writeln!(file, "{}", json).map_err(|e| format!("write audit log: {e}"))?;

        self.entries_written += 1;
        Ok(())
    }

    /// Clean up log files older than retention period.
    pub fn cleanup_old_logs(&self, current_day_number: u64) -> Result<u32, String> {
        if !self.log_dir.exists() {
            return Ok(0);
        }

        let retention_days = self.retention_days as u64;
        let mut removed = 0u32;

        let entries = fs::read_dir(&self.log_dir).map_err(|e| format!("read audit dir: {e}"))?;

        for entry in entries {
            let entry = entry.map_err(|e| format!("read dir entry: {e}"))?;
            let name = entry.file_name();
            let name_str = name.to_string_lossy();

            if name_str.starts_with("audit_") && name_str.ends_with(".jsonl") {
                let date_part = name_str
                    .trim_start_matches("audit_")
                    .trim_end_matches(".jsonl");
                if let Ok(day_num) = date_part.parse::<u64>() {
                    if current_day_number.saturating_sub(day_num) > retention_days {
                        fs::remove_file(entry.path())
                            .map_err(|e| format!("remove old log: {e}"))?;
                        removed += 1;
                    }
                }
            }
        }

        Ok(removed)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_record(sleeve_id: u8) -> AuditRecord {
        AuditRecord {
            timestamp_ns: 86400_000_000_000, // Day 1
            event_type: AuditEventType::SleeveSignal,
            sleeve_id,
            signal_value: 0.5,
            position_delta: 100.0,
            risk_flag: 0,
        }
    }

    #[test]
    fn test_audit_log_entry_from_record() {
        let record = make_record(1);
        let entry = AuditLogEntry::from_record(&record);
        assert_eq!(entry.event_type, "sleeve_signal");
        assert_eq!(entry.sleeve_id, 1);
        assert_eq!(entry.signal_value, 0.5);
    }

    #[test]
    fn test_event_type_mapping() {
        let types = vec![
            (AuditEventType::SleeveSignal, "sleeve_signal"),
            (AuditEventType::CrisisProtocol, "crisis_protocol"),
            (AuditEventType::ConfigUpdate, "config_update"),
            (AuditEventType::Heartbeat, "heartbeat"),
            (AuditEventType::CircuitBreaker, "circuit_breaker"),
        ];

        for (event_type, expected) in types {
            let record = AuditRecord {
                timestamp_ns: 86400_000_000_000,
                event_type,
                sleeve_id: 0,
                signal_value: 0.0,
                position_delta: 0.0,
                risk_flag: 0,
            };
            let entry = AuditLogEntry::from_record(&record);
            assert_eq!(entry.event_type, expected);
        }
    }

    #[test]
    fn test_log_file_path() {
        let logger = AuditLogger::new("/var/log/quantum", 2555);
        let path = logger.log_file_path("1");
        assert_eq!(path.to_str().unwrap(), "/var/log/quantum/audit_1.jsonl");
    }

    #[test]
    fn test_write_record() {
        let dir = std::env::temp_dir().join("qp_audit_test");
        let _ = fs::remove_dir_all(&dir);

        let mut logger = AuditLogger::new(dir.to_str().unwrap(), 2555);
        let record = make_record(1);

        logger.write_record(&record).unwrap();
        assert_eq!(logger.entries_written, 1);

        // Verify file exists and contains JSONL
        let log_path = logger.log_file_path(&logger.current_date);
        let content = fs::read_to_string(log_path).unwrap();
        assert!(content.contains("sleeve_signal"));
        assert!(content.contains("\"sleeve_id\":1"));

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_write_multiple_records() {
        let dir = std::env::temp_dir().join("qp_audit_multi");
        let _ = fs::remove_dir_all(&dir);

        let mut logger = AuditLogger::new(dir.to_str().unwrap(), 2555);

        for i in 0..5 {
            let record = make_record(i);
            logger.write_record(&record).unwrap();
        }
        assert_eq!(logger.entries_written, 5);

        let log_path = logger.log_file_path(&logger.current_date);
        let content = fs::read_to_string(log_path).unwrap();
        let lines: Vec<&str> = content.trim().lines().collect();
        assert_eq!(lines.len(), 5);

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_cleanup_old_logs() {
        let dir = std::env::temp_dir().join("qp_audit_cleanup");
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();

        // Create old and recent log files
        fs::write(dir.join("audit_1.jsonl"), "old").unwrap();
        fs::write(dir.join("audit_100.jsonl"), "recent").unwrap();

        let logger = AuditLogger::new(dir.to_str().unwrap(), 50);

        let removed = logger.cleanup_old_logs(110).unwrap();
        assert_eq!(removed, 1);

        // Recent file should remain
        assert!(dir.join("audit_100.jsonl").exists());
        // Old file should be removed
        assert!(!dir.join("audit_1.jsonl").exists());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_cleanup_nonexistent_dir() {
        let logger = AuditLogger::new("/nonexistent/dir", 2555);
        let removed = logger.cleanup_old_logs(100).unwrap();
        assert_eq!(removed, 0);
    }

    #[test]
    fn test_retention_days_default() {
        let logger = AuditLogger::new("/var/log/quantum", 2555);
        assert_eq!(logger.retention_days, 2555); // ~7 years
    }
}
