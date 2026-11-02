from rag_service.utils.queue_manager import QueueManager
import frappe, json

SINCE = "31-10-2026 17:00:34"    # edit: resend everything completed at/after this

qm = QueueManager()
for r in frappe.get_all(
    "Feedback Request",
    filters={"status": "Completed", "completed_at": [">=", SINCE]},
    fields=["name", "submission_id", "student_id", "assignment_id", "generated_feedback", "completed_at"],
    order_by="completed_at asc",
):
    qm.send_feedback_to_tap({
        "submission_id": r.submission_id,
        "student_id": r.student_id,
        "assignment_id": r.assignment_id,
        "feedback": json.loads(r.generated_feedback),
        "generated_at": r.completed_at.isoformat(),
    })
