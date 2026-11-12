"""Prevent early boot output, stale logs and late panics from becoming passes."""
import unittest

from nexuslib.qemu import CHECKS, analyze

TOKEN = "0123456789abcdef" * 2


def complete_log(token=TOKEN):
    return "\n".join([
        "== XNULOADER v3 ==", "Darwin Kernel Version 22.5.0: fixture",
        "BSD root: md0, major 1, minor 0", "NEXUS PROBE 1",
        *(f"NEXUS CHECK {name} PASS" for name in CHECKS),
        f"NEXUS RESULT PASS token={token}", "NEXUS HEARTBEAT", "NEXUS HEARTBEAT", "",
    ])


class EvidenceTests(unittest.TestCase):
    def test_complete(self):
        self.assertTrue(analyze(complete_log(), TOKEN)["passed"])

    def test_ansi_and_crlf(self):
        log = "\x1b[2J\x1b[01;01H" + complete_log().replace("\n", "\r\n")
        self.assertTrue(analyze(log, TOKEN)["passed"])

    def test_early_stages_are_not_a_boot(self):
        lines = complete_log().splitlines()
        for end in range(len(lines) - 1):
            with self.subTest(end=end):
                self.assertFalse(analyze("\n".join(lines[:end]), TOKEN)["passed"])

    def test_every_check_required(self):
        for name in CHECKS:
            with self.subTest(name=name):
                self.assertFalse(analyze(complete_log().replace(f"NEXUS CHECK {name} PASS\n", ""), TOKEN)["passed"])

    def test_check_order_required(self):
        log = complete_log().replace("NEXUS CHECK pid1 PASS\nNEXUS CHECK uid0 PASS",
                                     "NEXUS CHECK uid0 PASS\nNEXUS CHECK pid1 PASS")
        self.assertFalse(analyze(log, TOKEN)["passed"])

    def test_stale_token_and_no_token(self):
        for token in (None, "f" * 32, "", "[0-9]+", "a" * 33):
            with self.subTest(token=token):
                self.assertFalse(analyze(complete_log(), token)["passed"])

    def test_token_must_be_exact(self):
        self.assertFalse(analyze(complete_log(TOKEN + "f"), TOKEN)["passed"])

    def test_late_panic_invalidates_pass(self):
        result = analyze(complete_log() + "panic(cpu 0 caller 0xffff): initproc failed\n", TOKEN)
        self.assertFalse(result["passed"])
        self.assertIsNotNone(result["rejection"])

    def test_explicit_failure(self):
        for name in CHECKS:
            with self.subTest(name=name):
                result = analyze(complete_log().replace(f"CHECK {name} PASS", f"CHECK {name} FAIL"), TOKEN)
                self.assertFalse(result["passed"])
                self.assertIsNotNone(result["rejection"])

    def test_bootarg_echo_is_not_result(self):
        result = analyze(complete_log().replace("NEXUS RESULT PASS", "cmdline: NEXUS RESULT PASS"), TOKEN)
        self.assertFalse(result["passed"])

    def test_heartbeat_must_follow_result(self):
        log = "NEXUS HEARTBEAT\n" * 3 + complete_log().replace("NEXUS HEARTBEAT\n", "")
        self.assertFalse(analyze(log, TOKEN)["passed"])

    def test_firmware_stall_is_diagnosed_but_never_passes(self):
        log = "UEFI firmware (version 2024.02-2ubuntu0.10 built at 15:40:28)\r\n\x1b[2J\x1b[01;01H"
        result = analyze(log, TOKEN)
        self.assertFalse(result["passed"])
        self.assertEqual(result["stages"], [])
        self.assertIn("never reached the loader", result["diagnosis"])
        self.assertIn("No loader", analyze("unrelated output\n", TOKEN)["diagnosis"])

    def test_diagnostics_by_stage(self):
        for log, expected in (("", "No loader"), ("== XNULOADER v3 ==\n", "Loader reached"),
                              (complete_log().split("BSD root")[0], "Kernel reached")):
            with self.subTest(expected=expected):
                self.assertIn(expected, analyze(log, TOKEN)["diagnosis"])
