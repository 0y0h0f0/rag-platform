from app.schemas.doc_schema import DashboardStats


def test_dashboard_stats_schema() -> None:
    stats = DashboardStats(
        total_documents=3,
        indexed_documents=2,
        failed_documents=1,
        total_tasks=4,
        failed_tasks=1,
        total_chunks=12,
    )
    assert stats.total_documents == 3
    assert stats.total_chunks == 12
