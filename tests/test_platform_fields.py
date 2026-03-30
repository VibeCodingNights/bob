"""Tests for PlatformField model and PlatformFieldRegistry."""

import yaml

from bob.platform_fields import PlatformField, PlatformFieldRegistry, _safe_filename


# ── PlatformField model tests ────────────────────────────────────────


class TestPlatformField:
    def test_creation_with_defaults(self):
        f = PlatformField(name="email", label="Email address")
        assert f.name == "email"
        assert f.label == "Email address"
        assert f.required is False
        assert f.discovered == ""
        assert f.selector_hint == ""

    def test_creation_with_all_fields(self):
        f = PlatformField(
            name="wallet_address",
            label="Ethereum wallet address",
            required=True,
            discovered="2026-03-20",
            selector_hint="input#wallet",
        )
        assert f.name == "wallet_address"
        assert f.label == "Ethereum wallet address"
        assert f.required is True
        assert f.discovered == "2026-03-20"
        assert f.selector_hint == "input#wallet"


# ── _safe_filename tests ─────────────────────────────────────────────


class TestSafeFilename:
    def test_normal_name_unchanged(self):
        assert _safe_filename("devpost") == "devpost"

    def test_slashes_replaced(self):
        assert "/" not in _safe_filename("../../etc/passwd")
        assert "\\" not in _safe_filename("foo\\bar")

    def test_dotdot_replaced(self):
        result = _safe_filename("../secret")
        assert ".." not in result

    def test_leading_dot_prefixed(self):
        result = _safe_filename(".hidden")
        assert result.startswith("_")

    def test_empty_string_prefixed(self):
        result = _safe_filename("")
        assert result.startswith("_")


# ── PlatformFieldRegistry tests ──────────────────────────────────────


class TestPlatformFieldRegistry:
    def test_empty_registry_returns_empty_list(self, tmp_path):
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        assert reg.get_fields("devpost") == []

    def test_empty_yaml_file_returns_empty_list(self, tmp_path):
        (tmp_path / "devpost.yaml").write_text("")
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        assert reg.get_fields("devpost") == []

    def test_yaml_without_fields_key_returns_empty_list(self, tmp_path):
        (tmp_path / "devpost.yaml").write_text("something_else: true\n")
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        assert reg.get_fields("devpost") == []

    def test_add_field_and_get_fields(self, tmp_path):
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        field = PlatformField(name="email", label="Email", required=True)
        reg.add_field("devpost", field)
        fields = reg.get_fields("devpost")
        assert len(fields) == 1
        assert fields[0].name == "email"
        assert fields[0].label == "Email"
        assert fields[0].required is True

    def test_get_required_fields(self, tmp_path):
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        reg.add_field("devpost", PlatformField(name="email", label="Email", required=True))
        reg.add_field("devpost", PlatformField(name="bio", label="Bio", required=False))
        reg.add_field("devpost", PlatformField(name="team_name", label="Team name", required=True))

        required = reg.get_required_fields("devpost")
        assert len(required) == 2
        names = {f.name for f in required}
        assert names == {"email", "team_name"}

    def test_has_field(self, tmp_path):
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        reg.add_field("devpost", PlatformField(name="email", label="Email"))
        assert reg.has_field("devpost", "email") is True
        assert reg.has_field("devpost", "phone") is False

    def test_has_field_unknown_platform(self, tmp_path):
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        assert reg.has_field("unknown_platform", "email") is False

    def test_dedup_by_name(self, tmp_path):
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        reg.add_field("devpost", PlatformField(name="email", label="Email v1"))
        reg.add_field("devpost", PlatformField(name="email", label="Email v2"))
        fields = reg.get_fields("devpost")
        assert len(fields) == 1
        # First one wins
        assert fields[0].label == "Email v1"

    def test_yaml_persistence_roundtrip(self, tmp_path):
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        reg.add_field(
            "ethglobal",
            PlatformField(
                name="wallet",
                label="Wallet address",
                required=True,
                discovered="2026-03-20",
                selector_hint="input#wallet",
            ),
        )

        # Load from a fresh registry instance pointing to the same dir
        reg2 = PlatformFieldRegistry(base_dir=tmp_path)
        fields = reg2.get_fields("ethglobal")
        assert len(fields) == 1
        f = fields[0]
        assert f.name == "wallet"
        assert f.label == "Wallet address"
        assert f.required is True
        assert f.discovered == "2026-03-20"
        assert f.selector_hint == "input#wallet"

    def test_multiple_platforms_stored_independently(self, tmp_path):
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        reg.add_field("devpost", PlatformField(name="email", label="Email"))
        reg.add_field("ethglobal", PlatformField(name="wallet", label="Wallet"))

        assert len(reg.get_fields("devpost")) == 1
        assert reg.get_fields("devpost")[0].name == "email"
        assert len(reg.get_fields("ethglobal")) == 1
        assert reg.get_fields("ethglobal")[0].name == "wallet"

    def test_safe_filename_used_for_platform_names(self, tmp_path):
        reg = PlatformFieldRegistry(base_dir=tmp_path)
        reg.add_field("../../etc/passwd", PlatformField(name="x", label="X"))
        # File should be inside tmp_path, not outside it
        files = list(tmp_path.glob("*.yaml"))
        assert len(files) == 1
        assert files[0].parent == tmp_path
