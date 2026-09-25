"""graph 的纯判定矩阵；CLI 查询适配由 preflight/main 调用测试覆盖。"""

import unittest

import pytest

import graph

pytestmark = pytest.mark.unit


def child(id_, status="open", labels=("ready-for-agent",), assignee=None):
    return {"id": id_, "status": status, "labels": list(labels), "assignee": assignee}


class GraphDecisionTests(unittest.TestCase):
    def test_flat_result(self):
        self.assertEqual(graph.flat_result([], []), {"flat": False, "reason": "no_children"})
        self.assertEqual(graph.flat_result([child("p-1")], []), {"flat": True})
        self.assertEqual(
            graph.flat_result([child("p-1")], [{"id": "p-1.2"}, {"id": "p-1.1"}]),
            {"flat": False, "grandchildren": ["p-1.1", "p-1.2"]},
        )
        with self.assertRaises(ValueError):
            graph.flat_result([child("p-1")], [{"status": "open"}])

    def test_resume_done_and_multiple(self):
        self.assertEqual(
            graph.frontier_result([child("p-1", "in_progress")], ["p-1"]),
            {"next": "resume", "ticket_id": "p-1"},
        )
        self.assertEqual(graph.frontier_result([child("p-1", "closed")], ["p-1"]), {"next": "done"})
        result = graph.frontier_result(
            [child("p-1", "in_progress"), child("p-2", "in_progress")], ["p-1", "p-2"]
        )
        self.assertEqual(result["reason"], "multiple_in_progress")

    def test_ready_candidate_matrix(self):
        children = [child("p-1")]
        self.assertIsNone(graph.frontier_result(children, ["p-1"]))
        self.assertEqual(graph.frontier_result(children, ["p-1"], [])["reason"], "no_ready")
        self.assertEqual(
            graph.frontier_result(children, ["p-1"], [child("other-1")])["reason"],
            "next_ticket_not_ready",
        )
        self.assertEqual(
            graph.frontier_result(children, ["p-1"], [child("p-1")]),
            {"next": "claim", "ticket_id": "p-1"},
        )
        for candidate in (
            child("p-1", "closed"),
            child("p-1", labels=()),
            child("p-1", assignee="agent"),
        ):
            self.assertEqual(
                graph.frontier_result(children, ["p-1"], [candidate])["reason"],
                "invalid_ready_candidate",
            )


if __name__ == "__main__":
    unittest.main()
