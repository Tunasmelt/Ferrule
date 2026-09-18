import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services" / "compiler" / "python"))

from ferrule_compiler.openapi import Operation  # noqa: E402
from ferrule_compiler.store import Job, JobResumeError, Store, new_id  # noqa: E402


class CompilerStoreConcurrencyTests(unittest.TestCase):
    def test_concurrent_resumes_of_the_same_job_are_single_use(self) -> None:
        # A get-then-put resume (the original shape) lets two racing resumes
        # both pass the status check before either writes, so the loser's
        # write silently clobbers the winner's. resume_needs_input holds one
        # lock across the whole check-select-write sequence instead, so
        # exactly one of these concurrent calls must succeed.
        store = Store()
        options = (
            Operation("getPost", "GET", "/posts/{id}", "Get a post", "...", ()),
            Operation("getUser", "GET", "/users/{id}", "Get a user", "...", ()),
        )
        job = Job(new_id("job"), "resolve", "needs_input", options=options)
        store.put_job(job)

        def try_resume(choice: str) -> str:
            try:
                store.resume_needs_input(job.id, choice)
                return "succeeded"
            except JobResumeError as error:
                return error.reason

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(try_resume, ["getPost", "getUser"]))

        self.assertEqual(1, results.count("succeeded"))
        self.assertEqual(1, results.count("not_resumable"))

        final = store.get_job(job.id)
        assert final is not None
        assert final.result is not None
        winning_choice = final.result["operation"]["operation_id"]  # type: ignore[index]
        self.assertIn(winning_choice, {"getPost", "getUser"})


if __name__ == "__main__":
    unittest.main()
