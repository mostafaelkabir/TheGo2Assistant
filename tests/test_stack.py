# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""The one-command stack, checked as data.

Docker is not available in the fast tier, so what can be asserted here is the
shape: that the Compose file names the services the runbook relies on, that
the server is never reachable without a token, that nothing in the stack
points at the developer's host database, and that the smoke test fails when
a search comes back uncited. Standing the stack up is the ticket's manual
acceptance, recorded in its Outcome.
"""

from __future__ import annotations

import importlib.util
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from go2.evaluation import load_cases

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
STACK = ROOT / "deploy" / "stack"
GO2_SERVICES = ("init", "server", "worker", "seed")


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (STACK / "docker-compose.yml").read_text(encoding="utf-8")
    )
    return loaded


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stack_smoke", STACK / "smoke.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, list):
        return dict(item.split("=", 1) for item in env)
    return {key: str(value) for key, value in env.items()}


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


class TestCompose:
    """The services and the wiring between them."""

    def test_compose_declares_the_stack_services(self, compose: dict[str, Any]) -> None:
        services = set(compose["services"])
        assert {"db", "init", "server", "worker", "seed", "mongodb", "librechat"} <= services
        # LibreChat's parallel RAG stack would be a second copy of the corpus.
        assert not services & {"rag_api", "vectordb", "meilisearch"}

    def test_server_binds_all_interfaces_only_with_a_required_token(
        self, compose: dict[str, Any]
    ) -> None:
        server = compose["services"]["server"]
        command = server["command"]
        assert (
            command[command.index("--host") + 1] == "0.0.0.0"  # noqa: S104 -- asserting the compose file's bind, not binding anything.
        )
        # `${VAR:?message}` makes Compose refuse to start with the variable
        # unset, before any container exists.
        assert re.match(r"^\$\{GO2_HTTP_TOKEN:\?", _env(server)["GO2_HTTP_TOKEN"])

    def test_server_and_worker_share_one_database_url_inside_the_network(
        self, compose: dict[str, Any]
    ) -> None:
        for name in GO2_SERVICES:
            url = _env(compose["services"][name])["GO2_DATABASE_URL"]
            assert "@db:5432/" in url, name
            assert "5433" not in url, name
            assert "localhost" not in url, name

    def test_the_server_port_is_published_on_loopback_only(self, compose: dict[str, Any]) -> None:
        (mapping,) = compose["services"]["server"]["ports"]
        assert str(mapping).startswith("127.0.0.1:")

    def test_the_seed_runs_only_under_its_profile(self, compose: dict[str, Any]) -> None:
        # A plain `up` must never index the samples into a real workspace.
        assert compose["services"]["seed"]["profiles"] == ["samples"]
        assert all("profiles" not in compose["services"][n] for n in ("server", "worker"))

    def test_librechat_waits_for_a_healthy_server(self, compose: dict[str, Any]) -> None:
        # MCP servers are discovered once at LibreChat's start.
        depends = compose["services"]["librechat"]["depends_on"]
        assert depends["server"]["condition"] == "service_healthy"
        assert "healthcheck" in compose["services"]["server"]


class TestLibreChat:
    """The UI reaches exactly one server, with the token."""

    def test_librechat_config_targets_the_stack_server_and_allows_only_it(self) -> None:
        config = yaml.safe_load((STACK / "librechat.yaml").read_text(encoding="utf-8"))
        (entry,) = config["mcpServers"].values()
        assert entry["url"] == "http://server:8765/mcp"
        assert config["mcpSettings"]["allowedAddresses"] == ["server:8765"]
        assert "${GO2_HTTP_TOKEN}" in entry["headers"]["Authorization"]
        # Without the server's own instructions the model gets three tools and
        # none of the abstention discipline.
        assert entry["serverInstructions"] is True


class TestDockerfile:
    """The image installs what the lock file says, and runs unprivileged."""

    def test_dockerfile_installs_the_locked_dependencies_as_a_non_root_user(self) -> None:
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        syncs = [line for line in text.splitlines() if "uv sync" in line]
        assert syncs
        assert all("--locked" in line and "--no-dev" in line for line in syncs)
        assert text.index("\nUSER go2") > text.rindex("uv sync")
        assert 'ENTRYPOINT ["go2"]' in text


class TestSmoke:
    """The smoke's judgement, without a server."""

    def test_smoke_rejects_a_result_without_a_citation(self, smoke: ModuleType) -> None:
        uncited = {
            "sufficient_evidence": True,
            "passages": [{"title": "Acme MSA", "document_id": "d1", "citation": ""}],
        }
        with pytest.raises(smoke.SmokeError, match="none carries a citation"):
            smoke.check_search(uncited, expected_title="Acme")

    def test_smoke_rejects_a_refusal_of_the_sample_question(self, smoke: ModuleType) -> None:
        refused = {"sufficient_evidence": False, "best_score": 0.12, "guidance": "NOT ENOUGH"}
        with pytest.raises(smoke.SmokeError, match="evidence gate refused"):
            smoke.check_search(refused, expected_title="Acme")

    def test_smoke_rejects_a_citation_of_the_wrong_document(self, smoke: ModuleType) -> None:
        other = {
            "sufficient_evidence": True,
            "passages": [{"title": "Globex Quotation", "document_id": "d2", "citation": "G p.1"}],
        }
        with pytest.raises(smoke.SmokeError, match="no citation names 'Acme'"):
            smoke.check_search(other, expected_title="Acme")

    def test_smoke_returns_the_cited_document_id(self, smoke: ModuleType) -> None:
        result = {
            "sufficient_evidence": True,
            "passages": [
                {"title": "Globex Quotation", "document_id": "d2", "citation": "G p.1"},
                {"title": "Acme MSA Amendment", "document_id": "d1", "citation": "A §4"},
            ],
        }
        assert smoke.check_search(result, expected_title="acme") == "d1"

    def test_smoke_requires_every_tool(self, smoke: ModuleType) -> None:
        with pytest.raises(smoke.SmokeError, match="fetch_document"):
            smoke.check_tools({"search_documents", "list_documents"})

    def test_smoke_reads_the_env_file_it_sits_beside(
        self, smoke: ModuleType, tmp_path: Path
    ) -> None:
        env = tmp_path / ".env"
        env.write_text(
            '# comment\nGO2_PORT=9000\nGO2_HTTP_TOKEN="abc"\n\nBROKEN\n', encoding="utf-8"
        )
        assert smoke.read_env_file(env) == {"GO2_PORT": "9000", "GO2_HTTP_TOKEN": "abc"}
        assert smoke.read_env_file(tmp_path / "absent") == {}


class TestSamples:
    """The demo corpus and its eval set agree with each other."""

    def test_the_sample_eval_set_names_only_sample_documents(self) -> None:
        suite = load_cases(STACK / "samples" / "eval.yaml")
        assert suite.tenant == "demo"
        titles = [_nfc(p.name) for p in (STACK / "samples").iterdir() if p.suffix != ".yaml"]
        for case in suite.cases:
            if case.expect_no_answer:
                continue
            assert any(
                _nfc(expected) in title for expected in case.expect_documents for title in titles
            ), case.question

    def test_the_sample_eval_set_keeps_a_refusal_and_an_arabic_case(self) -> None:
        suite = load_cases(STACK / "samples" / "eval.yaml")
        assert any(case.expect_no_answer for case in suite.cases)
        assert any(re.search(r"[؀-ۿ]", case.question) for case in suite.cases)
