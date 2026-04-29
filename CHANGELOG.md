# CHANGELOG

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial public release
- Core data quality profiling with pandas
- Excel report generation with multiple sheets
- Streamlit web dashboard
- Cloud integration (AWS S3, Azure Blob Storage, Snowflake)
- Optional PySpark support for large-scale data
- Credential profile management
- Privacy mode for hiding source file paths

### Planned
- GCP Cloud Storage support
- Custom validation rules engine
- Anomaly detection capabilities
- REST API
- Performance optimizations
- Data catalog integrations

---

## [0.1.0] - 2026-04-29

### Added
- **Core Features**
  - Comprehensive data quality metrics (row/column counts, nulls, data types, min/max, uniqueness)
  - Support for CSV, JSON, Parquet, Excel formats
  - Multi-file batch profiling
  - Privacy mode (hide source paths)

- **Reporting**
  - Excel reports with 4 sheets: Overview, Column_Details, Dtype_Summary, Sample_Data
  - Single-file wide format and batch long tidy format
  - Streamlit interactive dashboard

- **Cloud Storage**
  - AWS S3 single bucket and all-buckets support
  - Azure Blob Storage with profile management
  - Snowflake connection support
  - Secure credential storage with gitignore

- **Big Data**
  - Optional PySpark profiler for large datasets
  - System temp-only processing (no project copy)

### Changed
- N/A (Initial release)

### Deprecated
- N/A (Initial release)

### Removed
- N/A (Initial release)

### Fixed
- N/A (Initial release)

### Security
- Credentials stored locally, never committed to git
- Support for AWS session tokens
- Secure connection testing before pipeline use

---

[Unreleased]: https://github.com/shubhamdhakne/DQ-tool/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/shubhamdhakne/DQ-tool/releases/tag/v0.1.0
