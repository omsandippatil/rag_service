# rag_service/rag_service/core/feedback_service.py

import frappe
import json
from datetime import datetime
from typing import Dict
from ..feedback_utils.evaluation_generation import EvaluationGenerator
from ..utils.queue_manager import QueueManager

class FeedbackService:
    def __init__(self):
        self.evaluation_generator = EvaluationGenerator(self)
        self.queue_manager = QueueManager()
        self.model_used = None

    async def generate_feedback( self, assignment_context: Dict, submission_data: Dict, submission_id: str,
                                    plagiarism_data: Dict = None, feedback_request_id: str = None) -> Dict:
        """Generate feedback with plagiarism context"""

        result_status = "Pending"
        model_used = "N/A"
        tempalate_used = "N/A"

        try:
            # Check for plagiarism/AI-generated content first
            if plagiarism_data:
                is_plagiarized = plagiarism_data.get("is_plagiarized", False)
                is_ai_generated = plagiarism_data.get("is_ai_generated", False)
                match_type = plagiarism_data.get("match_type", "original")
                # Rubric re-evaluations are always graded, whatever PLG reports.
                is_rubric = submission_data.get("eval_type") == "rubric"

                # Handle AI-generated submissions
                if is_ai_generated and not is_rubric:
                    result_status = "Success - Flagged"
                    feedback = self._create_ai_generated_feedback(
                        plagiarism_data
                    )
                    tempalate_used = "Feedback Template for AI Generated Submission"

                # Handle plagiarized submissions
                elif is_plagiarized and not is_rubric:
                    result_status = "Success - Flagged"
                    feedback = self._create_plagiarism_feedback(
                        plagiarism_data
                    )
                    tempalate_used = "Feedback Template for Plagiarized Submission"
                
                # Continue with normal feedback generation for original work
                else:
                    result_status = "Success - Original"
                    feedback, model_used, tempalate_used = await self.evaluation_generator.generate_ai_feedback(
                        assignment_context, submission_data, submission_id
                    )
            
            feedback["translation_language"] = assignment_context["student"].get("language", "English")
            await self._update_result_status(feedback_request_id, result_status)
            return feedback, model_used, tempalate_used

        except Exception as e:
            result_status = "Failed"
            await self._update_result_status(feedback_request_id, result_status, str(e))
            raise

    async def process_feedback(
        self, request_id: str, feedback: Dict, model_used: str, template_used: str,
    ) -> None:
        """Process and store feedback in Feedback Request DocType."""
        try:
            # Get the feedback request document
            feedback_request = frappe.get_doc("Feedback Request", request_id)
            # Update document fields using db_set
            feedback_request.db_set("status", "Completed", update_modified=True)
            feedback_request.db_set(
                "generated_feedback",
                json.dumps(feedback, indent=2, ensure_ascii=False),
                update_modified=True,
            )
            feedback_request.db_set("completed_at", datetime.now(), update_modified=True)
            feedback_request.db_set("model_used", model_used, update_modified=True)
            feedback_request.db_set("template_used", template_used, update_modified=True)

            # Commit changes
            frappe.db.commit()

            # Verify the update
            updated_doc = frappe.get_doc("Feedback Request", request_id)
            # Prepare and send message to TAP LMS
            message = {
                "submission_id": feedback_request.submission_id,
                "student_id": feedback_request.student_id,
                "assignment_id": feedback_request.assignment_id,
                "source": feedback_request.source,
                "feedback": feedback,
                "eval_type": feedback_request.eval_type,
                "model_used": model_used,
                "generated_at": feedback_request.completed_at.isoformat()
                if feedback_request.completed_at
                else datetime.now().isoformat(),
            }

            # Send to TAP LMS queue
            self.queue_manager.send_feedback_to_tap(message)

            print("Payload sent to TAP LMS queue:")
            print(json.dumps(message, indent=2, ensure_ascii=False))

        except Exception as e:
            error_msg = f"Error processing feedback: {str(e)}"
            print(f"\nError: {error_msg}")

            try:
                if "feedback_request" in locals() and feedback_request:
                    feedback_request.db_set("status", "Failed", update_modified=True)
                    feedback_request.db_set("error_log", error_msg, update_modified=True)
                    frappe.db.commit()
                    print(f"Request {request_id} marked as failed")
            except Exception as save_error:
                print(f"Error saving failure status: {str(save_error)}")

            frappe.log_error(error_msg, "Feedback Processing Error")
            raise

    async def _update_result_status(self, feedback_request_id: str, status: str, error_message: str = None):
        """Update Feedback Request result_status"""
        if not feedback_request_id:
            return

        update_data = {"result_status": status}
        if error_message:
            update_data["error_message"] = error_message[:500]  # Truncate long errors

        frappe.db.set_value(
            "Feedback Request",
            feedback_request_id,
            update_data,
            update_modified=True
        )
        frappe.db.commit()

    def create_text_submission_feedback(self, language: str) -> Dict:
        """Stock reply for text and emoji submissions, which are not graded."""
        messages = {
            "English": "Send me your completed activity champ! I am waiting to see what you have made",
            "Hindi": "चैंप, मुझे अपनी पूरी की हुई एक्टिविटी भेजें! मैं यह देखने का इंतज़ार कर रही हूँ कि आपने क्या बनाया है।",
            "Marathi": "चॅम्प, तुमची पूर्ण केलेली ॲक्टिव्हिटी मला पाठवा! तुम्ही काय बनवले आहे हे पाहण्यासाठी मी वाट पाहत आहे.",
            "Punjabi": "ਚੈਂਪ, ਮੈਨੂੰ ਆਪਣੀ ਪੂਰੀ ਕੀਤੀ ਐਕਟੀਵਿਟੀ ਭੇਜੋ! ਮੈਂ ਇਹ ਦੇਖਣ ਦੀ ਉਡੀਕ ਕਰ ਰਹੀ ਹਾਂ ਕਿ ਤੁਸੀਂ ਕੀ ਬਣਾਇਆ ਹੈ।",
            "Kannada": "ಚಾಂಪ್, ನಿಮ್ಮ ಪೂರ್ಣಗೊಳಿಸಿದ ಚಟುವಟಿಕೆಯನ್ನು ನನಗೆ ಕಳುಹಿಸಿ! ನೀವು ಏನು ಮಾಡಿದ್ದೀರಿ ಎಂದು ನೋಡಲು ನಾನು ಕಾಯುತ್ತಿದ್ದೇನೆ.",
        }
        return {
            "overall_feedback": messages["English"],
            "overall_feedback_translated": messages[language],
            "translation_language": language,
            "final_grade": 0,
            "submission_validity": "Invalid",
            "rubric_evaluations": [],
        }

    def _create_ai_generated_feedback(self, plagiarism_data: Dict) -> Dict:
        """Create feedback for AI-generated submissions"""

        ai_source = plagiarism_data.get("ai_detection_source", "unknown")
        ai_confidence = plagiarism_data.get("ai_confidence", 0.0)
        response = {
            "overall_feedback": "Hi Champ, I found you have sent AI created work. Please send your work. I'm excited to see what you made.",
            "overall_feedback_translated": "Your submission appears to be generated by an AI tool. \
            At MentorMe, we encourage original creative work that reflects your own learning \
            and artistic development. AI-generated images, while interesting, don't demonstrate \
            the skills and creativity we're looking to nurture. Please submit your own original \
            artwork for this assignment.",
            "strengths": ["N/A - AI-generated content detected."],
            "areas_for_improvement": ["Submit original artwork created by you",
                                      "Review assignment guidelines for creative direction"],
            "learning_objectives_feedback": ["N/A - AI-generated content detected."],
            "final_grade": 0,
            "submission_validity": "Invalid" ,
            "encouragement": "We believe in your creative abilities!",
            "rubric_evaluations": [{
                                        "Skill": "Content Knowledge",
                                        "grade_value": 0,
                                        "observation": "N/A - AI-generated content detected."
                                    }],
            "plagiarism_output": {
                "stock_audio_file": "invalid_submission_ai",
                "is_plagiarized": False,
                "is_ai_generated": True,
                "match_type": "ai_generated",
                "plagiarism_source": "none",
                "similarity_score": 0.0,
                "ai_detection_source": ai_source,
                "ai_confidence": ai_confidence,
            }
        }

        return response

    def _create_plagiarism_feedback( self, plagiarism_data: Dict) -> Dict:
        """Create feedback for plagiarized submissions"""

        match_type = plagiarism_data.get("match_type")
        plagiarism_source = plagiarism_data.get("plagiarism_source")
        similarity_score = plagiarism_data.get("similarity_score", 0.0)
        ai_confidence = plagiarism_data.get("ai_confidence", 0.0)
        
        if plagiarism_source =="peer":
            feedback = "Hi Champ, I found you have sent another student's work. Please send your work. No cheating this time. Excited to see what you made."
        elif plagiarism_source =="self":
            feedback = "Hi Champ, I found you have sent the same work again. Please resend the final work. Excited to see what you made."
        elif plagiarism_source == "reference":
            feedback = "Hi Champ, I found you have sent work that closely matches reference materials. Please submit your own original work. I'm excited to see your unique creation!"
        else:
            feedback = "Hi Champ, I found you have sent work that closely matches existing content. Please submit your own original work. I'm excited to see your unique creation!"
        # respond with structured feedback
        response = {
            "overall_feedback": feedback,
            "overall_feedback_translated": feedback,
            "strengths": ["N/A - Submission flagged for similarity"],
            "areas_for_improvement": ["Create original artwork for this assignment",
                                      "Review academic integrity guidelines"],
            "learning_objectives_feedback": ["N/A - Submission flagged for similarity"],
            "final_grade": 0,
            "submission_validity": "Invalid" ,
            "encouragement": "Every artist develops their unique style through practice!",
            "rubric_evaluations": [{
                                        "Skill": "Content Knowledge",
                                        "grade_value": 0,
                                        "observation": "N/A - Submission flagged for similarity."
                                    },
                                    {
                                        "Skill": "Creativity",
                                        "grade_value": 0,
                                        "observation": "N/A - Submission flagged for similarity."
                                    }],
            "plagiarism_output": {
                "stock_audio_file": "invalid_submission_ai",
                "is_plagiarized": True,
                "is_ai_generated": False,
                "match_type": match_type,
                "plagiarism_source": plagiarism_source,
                "similarity_score": similarity_score,
                "ai_detection_source": "none",
                "ai_confidence": ai_confidence,
            }
        }

        return response 

    def validate_feedback_structure(self, feedback: Dict, expected_format: Dict) -> Dict:
        """Ensure feedback has all required fields with correct types"""
        # Ensure all expected fields are present
        for field in expected_format:
            if field not in feedback:
                if isinstance(expected_format[field], list):
                    feedback[field] = ["No information provided"]
                elif isinstance(expected_format[field], (int, float)):
                    feedback[field] = 0
                else:
                    feedback[field] = "No information provided"
        
        # Validate final_grade format for TAP LMS compatibility
        try:
            grade = feedback.get("final_grade", 0)
            if isinstance(grade, str):
                # Extract numeric part only
                grade_clean = ''.join(c for c in grade if c.isdigit() or c == '.')
                grade = float(grade_clean) if grade_clean else 0
            feedback["final_grade"] = max(0, min(100, float(grade)))
        except (ValueError, TypeError):
            feedback["final_grade"] = 0
        
        # Ensure list fields are lists
        list_fields = ["strengths", "areas_for_improvement", "learning_objectives_feedback"]
        for field in list_fields:
            if field in feedback and not isinstance(feedback[field], list):
                feedback[field] = [str(feedback[field])]
        
        return feedback

    # def create_fallback_feedback(self, expected_format: Dict) -> Dict:
    #     """Create structured fallback when JSON parsing fails"""
        
    #     fallback = {}
    #     for field, default_value in expected_format.items():
    #         if field == "overall_feedback":
    #             fallback[field] = "I encountered a system error while processing your submission. This appears to be a technical issue on our end. Please try resubmitting, and if the issue persists, contact your instructor."
    #         elif field == "overall_feedback_translated":
    #             fallback[field] = "I encountered a system error while processing your submission. This appears to be a technical issue on our end. Please try resubmitting, and if the issue persists, contact your instructor."
    #         elif field == "final_grade":
    #             fallback[field] = 50  # Neutral grade for technical issues
    #         elif field == "rubric_evaluations":
    #             fallback[field] = [
    #             {
    #             "skill": "Content Knowledge",
    #             "grade_value": 2,
    #             "observation": "Neutral evaluation due to processing issue"
    #             }
    #         ]
    #         elif isinstance(default_value, list):
    #             if "strength" in field:
    #                 fallback[field] = ["Your submission was received and processed"]
    #             elif "improvement" in field:
    #                 fallback[field] = ["Please ensure your submission clearly shows your work"]
    #             else:
    #                 fallback[field] = ["Unable to provide specific feedback due to processing issue"]
    #         else:
    #             if field == "encouragement":
    #                 fallback[field] = "Technical issues don't reflect your effort - please try resubmitting!"
    #             else:
    #                 fallback[field] = "Processing issue - please resubmit for detailed feedback"
        
    #     return fallback

    def fail_request(self, request_id: str, error: str, **fields) -> None:
        """Mark a Feedback Request Failed and tell TAP LMS, so the submission doesn't wait forever."""
        frappe.db.set_value(
            "Feedback Request", request_id,
            {"status": "Failed", "error_log": str(error)[:1000], **fields},
        )
        frappe.db.commit()
        fr = frappe.get_doc("Feedback Request", request_id)
        try:
            self.queue_manager.send_feedback_to_tap({
                "submission_id": fr.submission_id,
                "student_id": fr.student_id,
                "assignment_id": fr.assignment_id,
                "source": fr.source,
                "eval_type": fr.eval_type,
                "status": "Failed",
                "feedback": self.create_error_feedback(str(error)),
                "generated_at": datetime.now().isoformat(),
            })
        except Exception as e:
            # Don't stop the caller's loop over the rest of the batch.
            frappe.log_error(
                f"Could not send failure for {request_id} to TAP LMS: {e}",
                "Feedback Failure Delivery Error",
            )

    def create_error_feedback(self, error_msg: str) -> Dict:
        """Create feedback for system errors"""

        feedback = {
            "overall_feedback": "I encountered a system error while processing your submission. This appears to be a technical issue on our end.",
            "overall_feedback_translated": "I encountered a system error while processing your submission. This appears to be a technical issue on our end. ",
            "strengths": [f"Your submission was received successfully but system encountered an error during processing.{error_msg}"],
            "areas_for_improvement": ["No issues identified with your submission - this appears to be a technical problem"],
            "learning_objectives_feedback": ["Unable to evaluate due to system error."],
            "final_grade": 0,
            "submission_validity": "Valid" ,
            "encouragement": "Technical issues don't reflect your effort or ability.",
            "error_message": error_msg,
            "rubric_evaluations": [{
                                        "Skill": "Content Knowledge",
                                        "grade_value": 2,
                                        "observation": "Neutral evaluation due to processing issue"
                                    }],
        }
        plagiarism_output = {
                "is_plagiarized": False,
                "is_ai_generated": False,
                "match_type": "original",
                "plagiarism_source": "none",
                "similarity_score": 0.0,
                "ai_detection_source": "none",
                "ai_confidence": 0.0,
                "similar_sources": []
            }
        feedback["plagiarism_output"] = plagiarism_output
        
        return feedback
