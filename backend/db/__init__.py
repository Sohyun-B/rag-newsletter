from .connection import get_db_connection, execute_query, execute_command, execute_insert_returning_id, test_connection
from .queries import (
    insert_email,
    get_unprocessed_emails,
    mark_email_processed,
    insert_chunk,
    get_chunks_by_chroma_ids,
    get_sync_state,
    update_sync_state,
    get_newsletters,
    get_newsletter_by_id,
    get_newsletter_count,
)
