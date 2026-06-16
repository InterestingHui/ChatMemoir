"""Unit tests for gui/ package — pure logic that doesn't need tkinter."""

import json
import os
import sys
import tempfile
from unittest import mock

import pytest

# Mock tkinter before gui imports
sys.modules['tkinter'] = mock.MagicMock()
sys.modules['tkinter.ttk'] = mock.MagicMock()

from gui import constants


# ── Constants ────────────────────────────────────────────────


class TestConstants:
    def test_colors_are_defined(self):
        assert constants.PRIMARY == "#07C160"
        assert constants.DANGER == "#FA5151"
        assert constants.BG == "#F0F2F5"
        assert constants.CARD_BG == "#FFFFFF"

    def test_color_is_valid_hex(self):
        for attr in ['PRIMARY', 'PRIMARY_HOVER', 'BG', 'CARD_BG', 'TEXT_PRIMARY',
                      'TEXT_SECONDARY', 'BORDER', 'DANGER']:
            val = getattr(constants, attr)
            assert val.startswith('#'), f"{attr} = {val} is not hex"
            assert len(val) == 7, f"{attr} = {val} bad hex length"


# ── _resource_path ───────────────────────────────────────────


class TestResourcePath:
    def test_dev_mode_path(self):
        assert getattr(sys, 'frozen', False) is False
        path = constants._resource_path('test_file.txt')
        assert path.endswith('test_file.txt')
        assert 'gui' not in path  # uses base_path which is project root

    def test_nested_resource(self):
        path = constants._resource_path('scribe/resources/template.html')
        assert path.endswith('scribe/resources/template.html')


# ── _load_config / _save_config ──────────────────────────────


class TestConfigIO:
    def test_load_config_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{}')
        try:
            with mock.patch.object(constants, '_CONFIG_PATH', f.name):
                cfg = constants._load_config()
                assert cfg == {}
        finally:
            os.unlink(f.name)

    def test_load_config_with_data(self):
        data = {"export_format": "HTML", "output_dir": "/tmp/out"}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
        try:
            with mock.patch.object(constants, '_CONFIG_PATH', f.name):
                cfg = constants._load_config()
                assert cfg == data
        finally:
            os.unlink(f.name)

    def test_load_config_nonexistent(self):
        with mock.patch.object(constants, '_CONFIG_PATH', '/nonexistent/config.json'):
            cfg = constants._load_config()
            assert cfg == {}

    def test_save_config(self):
        with tempfile.NamedTemporaryFile(mode='r', suffix='.json', delete=False) as f:
            cfg_path = f.name
        try:
            with mock.patch.object(constants, '_CONFIG_PATH', cfg_path):
                constants._save_config({"format": "TXT"})
            with open(cfg_path, 'r') as f:
                saved = json.load(f)
            assert saved == {"format": "TXT"}
        finally:
            os.unlink(cfg_path)

    def test_save_config_permission_error_handled(self):
        with mock.patch.object(constants, '_CONFIG_PATH', '/dev/null/readonly/conf.json'):
            # Should not raise
            constants._save_config({"x": 1})
