"""The recovery job must fail closed if the expected media disk is missing."""

import importlib.util
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "reconcile", Path(__file__).resolve().parents[1] / "ops/reconcile.py"
)
reconcile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconcile)


class RecoveryTests(unittest.TestCase):
    def test_complete_dashboard_stop_is_respected_without_changing_vpn_mode(self):
        with (
            patch.dict(reconcile.os.environ, {}, clear=True),
            patch.object(
                reconcile, "configured_services", return_value={"portal", "gluetun"}
            ),
            patch.object(
                reconcile,
                "inspect_services",
                return_value={
                    "portal": {"State": {"Status": "exited", "ExitCode": 0}},
                    "gluetun": {"State": {"Status": "exited", "ExitCode": 143}},
                },
            ),
            patch.object(reconcile, "was_manually_stopped", return_value=True),
            patch.object(reconcile, "switch_to_direct") as switch,
            patch.object(reconcile, "compose") as compose,
        ):
            reconcile.main()
            switch.assert_not_called()
            compose.assert_not_called()

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        marker = patch.object(
            reconcile, "DISK_RECOVERY", Path(folder.name) / "disk-missing"
        )
        marker.start()
        self.addCleanup(marker.stop)
        configured = patch.object(
            reconcile,
            "configured_services",
            return_value={"gluetun", "qbittorrent", "sonarr"},
        )
        configured.start()
        self.addCleanup(configured.stop)
        action = patch.object(reconcile, "stop_action", return_value="pause")
        action.start()
        self.addCleanup(action.stop)

    def test_disk_identity(self):
        with patch.object(reconcile.os.path, "ismount", return_value=False):
            self.assertFalse(reconcile.disk_ready("/media/Media", "1234"))
        with (
            patch.object(reconcile.os.path, "ismount", return_value=True),
            patch.object(
                reconcile.subprocess, "check_output", return_value="ABCD-1234\n"
            ),
        ):
            self.assertTrue(reconcile.disk_ready("/media/Media", "abcd-1234"))
            self.assertFalse(reconcile.disk_ready("/media/Media", "5678"))
            self.assertFalse(reconcile.disk_ready("/media/Media", ""))

    def test_missing_disk_stops_instead_of_starting(self):
        with (
            patch.dict(reconcile.os.environ, {"MEDIA_STACK_MOUNT": "/media/Media"}),
            patch.object(reconcile, "disk_ready", return_value=False),
            patch.object(reconcile, "compose") as compose,
        ):
            with self.assertRaises(SystemExit):
                reconcile.main()
            compose.assert_called_once_with("stop", "-t", "60")
            self.assertTrue(reconcile.DISK_RECOVERY.exists())

    def test_disk_return_recovers_even_when_all_containers_were_stopped(self):
        reconcile.DISK_RECOVERY.touch()
        with (
            patch.dict(reconcile.os.environ, {}, clear=True),
            patch.object(reconcile, "configured_services", return_value={"portal"}),
            patch.object(
                reconcile,
                "inspect_services",
                return_value={"portal": {"State": {"Status": "exited", "ExitCode": 0}}},
            ),
            patch.object(reconcile, "was_manually_stopped", return_value=True),
            patch.object(reconcile, "compose") as compose,
        ):
            reconcile.main()
            self.assertTrue(compose.called)
            self.assertFalse(reconcile.DISK_RECOVERY.exists())

    def test_vpn_namespace_is_repaired_before_waiting(self):
        vpn = {"Id": "vpn-new", "State": {"Running": True}}
        torrent = {"Id": "torrent", "State": {"Running": True}}
        with (
            patch.dict(reconcile.os.environ, {}, clear=True),
            patch.object(
                reconcile,
                "inspect_services",
                return_value={"gluetun": vpn, "qbittorrent": torrent},
            ),
            patch.object(reconcile, "namespace", side_effect=["net:[1]", "net:[2]"]),
            patch.object(reconcile, "compose") as compose,
        ):
            reconcile.main()
            calls = [c.args for c in compose.call_args_list]
            self.assertIn(
                (
                    "up",
                    "-d",
                    "--no-deps",
                    "--force-recreate",
                    "--no-build",
                    "--pull",
                    "never",
                    "qbittorrent",
                ),
                calls,
            )
            self.assertIn("--wait", calls[-1])

    def test_stopped_vpn_does_not_block_other_apps_or_get_restarted(self):
        with (
            patch.dict(reconcile.os.environ, {}, clear=True),
            patch.object(
                reconcile,
                "inspect_services",
                side_effect=[
                    {
                        "gluetun": {"State": {"Status": "exited", "ExitCode": 0}},
                    },
                    {},
                ],
            ),
            patch.object(reconcile, "compose") as compose,
        ):
            reconcile.main()
            for call in compose.call_args_list:
                self.assertIn("sonarr", call.args)
                self.assertNotIn("gluetun", call.args)
                self.assertNotIn("qbittorrent", call.args)

    def test_disabled_vpn_orphan_is_ignored(self):
        with (
            patch.dict(reconcile.os.environ, {}, clear=True),
            patch.object(reconcile, "configured_services", return_value={"sonarr"}),
            patch.object(
                reconcile,
                "inspect_services",
                side_effect=[
                    {
                        "gluetun": {"State": {"Health": {"Status": "unhealthy"}}},
                    },
                    {},
                ],
            ),
            patch.object(reconcile, "compose") as compose,
        ):
            reconcile.main()
            self.assertFalse(
                any(c.args[0] == "restart" for c in compose.call_args_list)
            )

    def test_authorized_manual_stop_switches_to_direct_and_refreshes_services(self):
        with (
            patch.dict(reconcile.os.environ, {}, clear=True),
            patch.object(reconcile, "stop_action", return_value="direct"),
            patch.object(reconcile, "was_manually_stopped", return_value=True),
            patch.object(reconcile, "switch_to_direct") as switch,
            patch.object(
                reconcile,
                "configured_services",
                side_effect=[
                    {"gluetun", "qbittorrent", "sonarr"},
                    {"qbittorrent", "sonarr"},
                ],
            ),
            patch.object(
                reconcile,
                "inspect_services",
                side_effect=[
                    {"gluetun": {"State": {"Status": "exited", "ExitCode": 0}}},
                    {},
                    {},
                ],
            ),
            patch.object(reconcile, "compose") as compose,
        ):
            reconcile.main()
            switch.assert_called_once_with()
            for call in compose.call_args_list:
                self.assertIn("qbittorrent", call.args)
                self.assertNotIn("gluetun", call.args)

    def test_clean_app_exit_without_stop_event_does_not_remove_vpn(self):
        with (
            patch.dict(reconcile.os.environ, {}, clear=True),
            patch.object(reconcile, "stop_action", return_value="direct"),
            patch.object(reconcile, "was_manually_stopped", return_value=False),
            patch.object(reconcile, "switch_to_direct") as switch,
            patch.object(
                reconcile,
                "inspect_services",
                side_effect=[
                    {"gluetun": {"State": {"Status": "exited", "ExitCode": 0}}},
                    {},
                ],
            ),
            patch.object(reconcile, "compose"),
        ):
            reconcile.main()
            switch.assert_not_called()

    def test_docker_stop_evidence_must_follow_the_container_exit(self):
        container = {
            "Id": "vpn-id",
            "State": {
                "Status": "exited",
                "ExitCode": 0,
                "FinishedAt": "2026-10-24T15:00:00.123456789Z",
            },
        }
        finished = reconcile.datetime.fromisoformat(
            "2026-10-24T15:00:00.123456+00:00"
        ).timestamp()
        with patch.object(
            reconcile.subprocess,
            "check_output",
            return_value='{"timeNano": ' + str(int((finished + 0.1) * 1e9)) + "}\n",
        ):
            self.assertTrue(reconcile.was_manually_stopped(container))
        with patch.object(
            reconcile.subprocess,
            "check_output",
            return_value='{"timeNano": ' + str(int((finished - 20) * 1e9)) + "}\n",
        ):
            self.assertFalse(reconcile.was_manually_stopped(container))
        with patch.object(reconcile.subprocess, "check_output", return_value=""):
            self.assertFalse(reconcile.was_manually_stopped(container))

    def test_unhealthy_vpn_stops_downloads_before_restarting(self):
        with (
            patch.dict(reconcile.os.environ, {}, clear=True),
            patch.object(
                reconcile,
                "inspect_services",
                side_effect=[
                    {
                        "gluetun": {"State": {"Health": {"Status": "unhealthy"}}},
                        "qbittorrent": {"State": {"Health": {"Status": "unhealthy"}}},
                        "sonarr": {"State": {"Health": {"Status": "unhealthy"}}},
                    },
                    {},
                ],
            ),
            patch.object(reconcile, "compose") as compose,
        ):
            reconcile.main()
            calls = [c.args for c in compose.call_args_list]
            self.assertEqual(
                calls[:3],
                [
                    ("stop", "qbittorrent"),
                    ("restart", "--no-deps", "gluetun"),
                    ("restart", "--no-deps", "sonarr"),
                ],
            )
