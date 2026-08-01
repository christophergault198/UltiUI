"""Tests for the probe-report path traversal fix in routes/printer.py.

The probe report filename originates from a Content-Disposition header on
the *printer's* HTTP response, which is not trusted input, so it must never
be able to make the server write outside its reports directory.
"""
from routes.printer import (
    DEFAULT_PROBE_REPORT_FILENAME,
    _is_within_directory,
    _parse_probe_report_filename,
    _sanitize_probe_filename,
)


def test_parse_filename_from_quoted_header():
    header = 'attachment; filename="report_123.json"'
    assert _parse_probe_report_filename(header) == 'report_123.json'


def test_parse_filename_from_unquoted_header():
    header = 'attachment; filename=report_123.json'
    assert _parse_probe_report_filename(header) == 'report_123.json'


def test_parse_filename_falls_back_when_header_missing_filename():
    assert _parse_probe_report_filename('attachment') == DEFAULT_PROBE_REPORT_FILENAME
    assert _parse_probe_report_filename('') == DEFAULT_PROBE_REPORT_FILENAME


def test_sanitize_strips_directory_traversal():
    assert _sanitize_probe_filename('../../etc/passwd') == 'passwd'
    assert _sanitize_probe_filename('../../../../etc/cron.d/evil') == 'evil'
    assert _sanitize_probe_filename('/etc/passwd') == 'passwd'


def test_sanitize_rejects_empty_or_dot_paths():
    assert _sanitize_probe_filename('') == DEFAULT_PROBE_REPORT_FILENAME
    assert _sanitize_probe_filename('.') == DEFAULT_PROBE_REPORT_FILENAME
    assert _sanitize_probe_filename('..') == DEFAULT_PROBE_REPORT_FILENAME
    assert _sanitize_probe_filename('   ') == DEFAULT_PROBE_REPORT_FILENAME


def test_sanitize_keeps_a_normal_filename():
    assert _sanitize_probe_filename('probe_report_2026.json') == 'probe_report_2026.json'


def test_is_within_directory(tmp_path):
    reports_dir = tmp_path / 'reports'
    reports_dir.mkdir()
    inside = reports_dir / 'report.json'
    outside = tmp_path / 'outside.json'

    assert _is_within_directory(str(reports_dir), str(inside))
    assert not _is_within_directory(str(reports_dir), str(outside))
