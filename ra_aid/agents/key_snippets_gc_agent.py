"""
Key snippets gc agent implementation.

This agent is responsible for maintaining the code snippet knowledge base by pruning less important
snippets when the total number exceeds a specified threshold. The agent evaluates all
key snippets and deletes the least valuable ones to keep the database clean and relevant.
"""

from typing import List

from langchain_core.tools import tool
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from ra_aid.agent_utils import create_agent, run_agent_with_retry
from ra_aid.database.repositories.key_snippet_repository import KeySnippetRepository
from ra_aid.database.repositories.human_input_repository import HumanInputRepository
from ra_aid.llm import initialize_llm
from ra_aid.prompts.key_snippets_gc_prompts import KEY_SNIPPETS_GC_PROMPT
from ra_aid.tools.memory import log_work_event, _global_memory


console = Console()
key_snippet_repository = KeySnippetRepository()
human_input_repository = HumanInputRepository()


@tool
def delete_key_snippets(snippet_ids: List[int]) -> str:
    """Delete multiple key snippets from the database by their IDs.
    Silently skips any IDs that don't exist.

    Args:
        snippet_ids: List of snippet IDs to delete
        
    Returns:
        str: Success or failure message
    """
    results = []
    not_found_snippets = []
    failed_snippets = []
    protected_snippets = []
    
    # Try to get the current human input to protect its snippets
    current_human_input_id = None
    try:
        recent_inputs = human_input_repository.get_recent(1)
        if recent_inputs and len(recent_inputs) > 0:
            current_human_input_id = recent_inputs[0].id
    except Exception as e:
        console.print(f"Warning: Could not retrieve current human input: {str(e)}")
    
    for snippet_id in snippet_ids:
        # Get the snippet first to capture filepath for the message
        snippet = key_snippet_repository.get(snippet_id)
        if snippet:
            filepath = snippet.filepath
            
            # Check if this snippet is associated with the current human input
            if current_human_input_id is not None and snippet.human_input_id == current_human_input_id:
                protected_snippets.append((snippet_id, filepath))
                continue
                
            # Delete from database if not protected
            success = key_snippet_repository.delete(snippet_id)
            if success:
                success_msg = f"Successfully deleted snippet #{snippet_id} from {filepath}"
                console.print(
                    Panel(
                        Markdown(success_msg), title="Snippet Deleted", border_style="green"
                    )
                )
                results.append((snippet_id, filepath))
                log_work_event(f"Deleted snippet {snippet_id}.")
            else:
                failed_snippets.append(snippet_id)
        else:
            not_found_snippets.append(snippet_id)

    # Prepare result message
    result_parts = []
    if results:
        deleted_msg = "Successfully deleted snippets:\n" + "\n".join([f"- #{snippet_id}: {filepath}" for snippet_id, filepath in results])
        result_parts.append(deleted_msg)
    
    if protected_snippets:
        protected_msg = "Protected snippets (associated with current request):\n" + "\n".join([f"- #{snippet_id}: {filepath}" for snippet_id, filepath in protected_snippets])
        result_parts.append(protected_msg)
        console.print(
            Panel(Markdown(protected_msg), title="Snippets Protected", border_style="blue")
        )
    
    if not_found_snippets:
        not_found_msg = f"Snippets not found: {', '.join([f'#{snippet_id}' for snippet_id in not_found_snippets])}"
        result_parts.append(not_found_msg)
    
    if failed_snippets:
        failed_msg = f"Failed to delete snippets: {', '.join([f'#{snippet_id}' for snippet_id in failed_snippets])}"
        result_parts.append(failed_msg)
    
    return "Snippets deleted."


def run_key_snippets_gc_agent() -> None:
    """Run the key snippets gc agent to maintain a reasonable number of key snippets.
    
    The agent analyzes all key snippets and determines which are the least valuable,
    deleting them to maintain a manageable collection size of high-value snippets.
    Snippets associated with the current human input are excluded from deletion.
    """
    # Get the count of key snippets
    snippets = key_snippet_repository.get_all()
    snippet_count = len(snippets)
    
    # Display status panel with snippet count included
    console.print(Panel(f"Gathering my thoughts...\nCurrent number of key snippets: {snippet_count}", title="🗑 Garbage Collection"))
    
    # Only run the agent if we actually have snippets to clean
    if snippet_count > 0:
        # Try to get the current human input ID to exclude its snippets
        current_human_input_id = None
        try:
            recent_inputs = human_input_repository.get_recent(1)
            if recent_inputs and len(recent_inputs) > 0:
                current_human_input_id = recent_inputs[0].id
        except Exception as e:
            console.print(f"Warning: Could not retrieve current human input: {str(e)}")
        
        # Get all snippets that are not associated with the current human input
        eligible_snippets = []
        protected_snippets = []
        for snippet in snippets:
            if current_human_input_id is not None and snippet.human_input_id == current_human_input_id:
                protected_snippets.append(snippet)
            else:
                eligible_snippets.append(snippet)
        
        # Only process if we have snippets that can be deleted
        if eligible_snippets:
            # Get eligible snippets as a formatted string for the prompt
            snippets_dict = {
                snippet.id: {
                    'filepath': snippet.filepath,
                    'line_number': snippet.line_number,
                    'snippet': snippet.snippet,
                    'description': snippet.description
                } 
                for snippet in eligible_snippets
            }
            
            formatted_snippets = "\n".join([
                f"Snippet #{k}: filepath={v['filepath']}, line_number={v['line_number']}, description={v['description']}\n```python\n{v['snippet']}\n```" 
                for k, v in snippets_dict.items()
            ])
            
            # Retrieve configuration
            llm_config = _global_memory.get("config", {})

            # Initialize the LLM model
            model = initialize_llm(
                llm_config.get("provider", "anthropic"),
                llm_config.get("model", "claude-3-7-sonnet-20250219"),
                temperature=llm_config.get("temperature")
            )
            
            # Create the agent with the delete_key_snippets tool
            agent = create_agent(model, [delete_key_snippets])
            
            # Format the prompt with the eligible snippets
            prompt = KEY_SNIPPETS_GC_PROMPT.format(key_snippets=formatted_snippets)
            
            # Set up the agent configuration
            agent_config = {
                "recursion_limit": 50  # Set a reasonable recursion limit
            }
            
            # Run the agent
            run_agent_with_retry(agent, prompt, agent_config)
            
            # Get updated count
            updated_snippets = key_snippet_repository.get_all()
            updated_count = len(updated_snippets)
            
            # Show info panel with updated count and protected snippets count
            protected_count = len(protected_snippets)
            if protected_count > 0:
                console.print(
                    Panel(
                        f"Cleaned key snippets: {snippet_count} → {updated_count}\nProtected snippets (associated with current request): {protected_count}",
                        title="🗑 GC Complete"
                    )
                )
            else:
                console.print(
                    Panel(
                        f"Cleaned key snippets: {snippet_count} → {updated_count}",
                        title="🗑 GC Complete"
                    )
                )
        else:
            console.print(Panel(f"All {len(protected_snippets)} snippets are associated with the current request and protected from deletion.", title="🗑 GC Info"))
    else:
        console.print(Panel("No key snippets to clean.", title="🗑 GC Info"))