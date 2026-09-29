from __future__ import annotations

from arcbench_agent_runtime import AgentRuntime


def sdk_usage_example() -> None:
    # Load ARC-Bench paths from environment variables injected by the runner.
    runtime = AgentRuntime.from_env()

    # Initialize the traceability store under `.arc/traceability/`.
    runtime.traceability.init_db()

    # Mark a requirement node as having completed the design phase.
    runtime.events.mark_design_done("REQ-1", "Design completed")

    # Register or update a requirement record with its scenario structure.
    runtime.traceability.upsert_requirement(
        req_id="REQ-1",
        name="Login",
        description="User can log in",
        scenarios=[
            {
                "id": "REQ-1-SCN-1",
                "name": "Happy path",
                "steps": [
                    {"keyword": "GIVEN", "content": "user opens the login page"},
                    {"keyword": "WHEN", "content": "user submits valid credentials"},
                    {"keyword": "THEN", "content": "user enters the home page"},
                ],
            }
        ],
    )

    # Register an implementation interface and link it back to its requirement.
    runtime.traceability.upsert_interface(
        interface_id="IF-LOGIN-API",
        req_ids=["REQ-1"],
        type="API",
        content="POST /api/auth/login",
        file_path="backend/src/routes/auth.py",
        first_line="18",
        implemented=False,
    )

    # Register a test record and link it to the requirement and interface.
    runtime.traceability.upsert_test(
        test_id="TEST-LOGIN-E2E",
        req_id="REQ-1",
        type="E2E",
        file_path="tests/login.spec.ts",
        first_line="7",
        interface_ids=["IF-LOGIN-API"],
    )

    # Mark the interface as implemented once the source code exists.
    runtime.traceability.set_interface_implemented(
        "IF-LOGIN-API",
        True,
        "Login endpoint is implemented",
    )

    # Mark the test as passing after the agent has run or reasoned about validation.
    runtime.traceability.set_test_pass_status("TEST-LOGIN-E2E", True)

    # Mark the requirement node state so ARC-Bench can visualize progress.
    runtime.traceability.upsert_node_state("REQ-1", "PASSED")

    # Ensure the generated project is a git repo with an initial baseline commit.
    runtime.git.ensure_repo(create_initial_commit=True)

    # Commit meaningful changes so the platform can inspect implementation history.
    runtime.git.commit("REQ-1 (design): Login")


def skill_usage_example() -> None:
    
    """
     --- arcbench-checkpoint ---
    
    Use this skill when your agent needs resumable task management. It is
    intended for long or multi-step implementation runs where the agent should
    record milestones, preserve enough state to resume after interruption, and
    make progress visible to the ARC-Bench runner.

    --- arcbench-runtime-signals ---
    
    Use this skill when your agent runs build, install, preview-server, or test
    commands and wants to report runtime status. It helps write structured
    runner events for actions such as "build started", "server ready",
    "tests passed", or "validation failed".
    
    --- arcbench-traceability ---
    
    Use this skill when your agent needs to connect requirement-tree items to
    implementation evidence. It is meant for recording which interfaces,
    files, tests, and pass/fail states satisfy each requirement, so ARC-Bench
    can visualize coverage and evaluate work against the requirement tree.
    
    """

    pass
