"""
Tests for the TrajectoryRepository class.
"""

import pytest
import datetime
import json
from unittest.mock import patch

import peewee

from ra_aid.database.connection import DatabaseManager, db_var
from ra_aid.database.models import Trajectory, HumanInput, Session, BaseModel
from ra_aid.database.repositories.trajectory_repository import (
    TrajectoryRepository,
    TrajectoryRepositoryManager,
    get_trajectory_repository,
    trajectory_repo_var
)
from ra_aid.database.pydantic_models import TrajectoryModel


@pytest.fixture
def cleanup_db():
    """Reset the database contextvar and connection state after each test."""
    # Reset before the test
    db = db_var.get()
    if db is not None:
        try:
            if not db.is_closed():
                db.close()
        except Exception:
            # Ignore errors when closing the database
            pass
    db_var.set(None)
    
    # Run the test
    yield
    
    # Reset after the test
    db = db_var.get()
    if db is not None:
        try:
            if not db.is_closed():
                db.close()
        except Exception:
            # Ignore errors when closing the database
            pass
    db_var.set(None)


@pytest.fixture
def cleanup_repo():
    """Reset the repository contextvar after each test."""
    # Reset before the test
    trajectory_repo_var.set(None)
    
    # Run the test
    yield
    
    # Reset after the test
    trajectory_repo_var.set(None)


@pytest.fixture
def setup_db(cleanup_db):
    """Set up an in-memory database with the necessary tables and patch the BaseModel.Meta.database."""
    # Initialize an in-memory database connection
    with DatabaseManager(in_memory=True) as db:
        # Patch the BaseModel.Meta.database to use our in-memory database
        with patch.object(BaseModel._meta, 'database', db):
            # Create the required tables
            with db.atomic():
                db.create_tables([Trajectory, HumanInput, Session], safe=True)
            
            yield db
            
            # Clean up
            with db.atomic():
                Trajectory.drop_table(safe=True)
                HumanInput.drop_table(safe=True)
                Session.drop_table(safe=True)


@pytest.fixture
def sample_human_input(setup_db):
    """Create a sample human input in the database."""
    return HumanInput.create(
        content="Test human input",
        source="test"
    )


@pytest.fixture
def test_tool_parameters():
    """Return test tool parameters."""
    return {
        "pattern": "test pattern",
        "file_path": "/path/to/file",
        "options": {
            "case_sensitive": True,
            "whole_words": False
        }
    }


@pytest.fixture
def test_tool_result():
    """Return test tool result."""
    return {
        "matches": [
            {"line": 10, "content": "This is a test pattern"},
            {"line": 20, "content": "Another test pattern here"}
        ],
        "total_matches": 2,
        "execution_time": 0.5
    }


@pytest.fixture
def test_step_data():
    """Return test step data for UI rendering."""
    return {
        "display_type": "text",
        "content": "Tool execution results",
        "highlights": [
            {"start": 10, "end": 15, "color": "red"}
        ]
    }


@pytest.fixture
def sample_trajectory(setup_db, sample_human_input, test_tool_parameters, test_tool_result, test_step_data):
    """Create a sample trajectory in the database."""
    return Trajectory.create(
        human_input=sample_human_input,
        tool_name="ripgrep_search",
        tool_parameters=json.dumps(test_tool_parameters),
        tool_result=json.dumps(test_tool_result),
        step_data=json.dumps(test_step_data),
        record_type="tool_execution",
        cost=0.001,
        tokens=100,
        is_error=False
    )


def test_create_trajectory(setup_db, sample_human_input, test_tool_parameters, test_tool_result, test_step_data):
    """Test creating a trajectory with all fields."""
    # Set up repository
    repo = TrajectoryRepository(db=setup_db)
    
    # Create a trajectory
    trajectory = repo.create(
        tool_name="ripgrep_search",
        tool_parameters=test_tool_parameters,
        tool_result=test_tool_result,
        step_data=test_step_data,
        record_type="tool_execution",
        human_input_id=sample_human_input.id,
        cost=0.001,
        tokens=100
    )
    
    # Verify type is TrajectoryModel, not Trajectory
    assert isinstance(trajectory, TrajectoryModel)
    
    # Verify the trajectory was created correctly
    assert trajectory.id is not None
    assert trajectory.tool_name == "ripgrep_search"
    
    # Verify the JSON fields are dictionaries, not strings
    assert isinstance(trajectory.tool_parameters, dict)
    assert isinstance(trajectory.tool_result, dict)
    assert isinstance(trajectory.step_data, dict)
    
    # Verify the nested structure of tool parameters
    assert trajectory.tool_parameters["options"]["case_sensitive"] == True
    assert trajectory.tool_result["total_matches"] == 2
    assert trajectory.step_data["highlights"][0]["color"] == "red"
    
    # Verify foreign key reference
    assert trajectory.human_input_id == sample_human_input.id


def test_create_trajectory_minimal(setup_db):
    """Test creating a trajectory with minimal fields."""
    # Set up repository
    repo = TrajectoryRepository(db=setup_db)
    
    # Create a trajectory with minimal fields
    trajectory = repo.create(
        tool_name="simple_tool"
    )
    
    # Verify type is TrajectoryModel, not Trajectory
    assert isinstance(trajectory, TrajectoryModel)
    
    # Verify the trajectory was created correctly
    assert trajectory.id is not None
    assert trajectory.tool_name == "simple_tool"
    
    # Verify optional fields are None
    assert trajectory.tool_parameters is None
    assert trajectory.tool_result is None
    assert trajectory.step_data is None
    assert trajectory.human_input_id is None
    assert trajectory.cost is None
    assert trajectory.tokens is None
    assert trajectory.is_error is False


def test_get_trajectory(setup_db, sample_trajectory, test_tool_parameters, test_tool_result, test_step_data):
    """Test retrieving a trajectory by ID."""
    # Set up repository
    repo = TrajectoryRepository(db=setup_db)
    
    # Get the trajectory by ID
    trajectory = repo.get(sample_trajectory.id)
    
    # Verify type is TrajectoryModel, not Trajectory
    assert isinstance(trajectory, TrajectoryModel)
    
    # Verify the retrieved trajectory matches the original
    assert trajectory.id == sample_trajectory.id
    assert trajectory.tool_name == sample_trajectory.tool_name
    
    # Verify the JSON fields are dictionaries, not strings
    assert isinstance(trajectory.tool_parameters, dict)
    assert isinstance(trajectory.tool_result, dict)
    assert isinstance(trajectory.step_data, dict)
    
    # Verify the content of JSON fields
    assert trajectory.tool_parameters == test_tool_parameters
    assert trajectory.tool_result == test_tool_result
    assert trajectory.step_data == test_step_data
    
    # Verify non-existent trajectory returns None
    non_existent_trajectory = repo.get(999)
    assert non_existent_trajectory is None


def test_update_trajectory(setup_db, sample_trajectory):
    """Test updating a trajectory."""
    # Set up repository
    repo = TrajectoryRepository(db=setup_db)
    
    # New data for update
    new_tool_result = {
        "matches": [
            {"line": 15, "content": "Updated test pattern"}
        ],
        "total_matches": 1,
        "execution_time": 0.3
    }
    
    new_step_data = {
        "display_type": "html",
        "content": "Updated UI rendering",
        "highlights": []
    }
    
    # Update the trajectory
    updated_trajectory = repo.update(
        trajectory_id=sample_trajectory.id,
        tool_result=new_tool_result,
        step_data=new_step_data,
        cost=0.002,
        tokens=200,
        is_error=True,
        error_message="Test error",
        error_type="TestErrorType",
        error_details="Detailed error information"
    )
    
    # Verify type is TrajectoryModel, not Trajectory
    assert isinstance(updated_trajectory, TrajectoryModel)
    
    # Verify the fields were updated
    assert updated_trajectory.tool_result == new_tool_result
    assert updated_trajectory.step_data == new_step_data
    assert updated_trajectory.cost == 0.002
    assert updated_trajectory.tokens == 200
    assert updated_trajectory.is_error is True
    assert updated_trajectory.error_message == "Test error"
    assert updated_trajectory.error_type == "TestErrorType"
    assert updated_trajectory.error_details == "Detailed error information"
    
    # Original tool parameters should not change
    # We need to parse the JSON string from the Peewee object for comparison
    original_params = json.loads(sample_trajectory.tool_parameters)
    assert updated_trajectory.tool_parameters == original_params
    
    # Verify updating a non-existent trajectory returns None
    non_existent_update = repo.update(trajectory_id=999, cost=0.005)
    assert non_existent_update is None


def test_delete_trajectory(setup_db, sample_trajectory):
    """Test deleting a trajectory."""
    # Set up repository
    repo = TrajectoryRepository(db=setup_db)
    
    # Verify the trajectory exists
    assert repo.get(sample_trajectory.id) is not None
    
    # Delete the trajectory
    result = repo.delete(sample_trajectory.id)
    
    # Verify the trajectory was deleted
    assert result is True
    assert repo.get(sample_trajectory.id) is None
    
    # Verify deleting a non-existent trajectory returns False
    result = repo.delete(999)
    assert result is False


def test_get_all_trajectories(setup_db, sample_human_input):
    """Test retrieving all trajectories."""
    # Set up repository
    repo = TrajectoryRepository(db=setup_db)
    
    # Create multiple trajectories
    for i in range(3):
        repo.create(
            tool_name=f"tool_{i}",
            tool_parameters={"index": i},
            human_input_id=sample_human_input.id
        )
    
    # Get all trajectories
    trajectories = repo.get_all()
    
    # Verify we got a dictionary of TrajectoryModel objects
    assert len(trajectories) == 3
    for trajectory_id, trajectory in trajectories.items():
        assert isinstance(trajectory, TrajectoryModel)
        assert isinstance(trajectory.tool_parameters, dict)
    
    # Verify the trajectories have the correct tool names
    tool_names = {trajectory.tool_name for trajectory in trajectories.values()}
    assert "tool_0" in tool_names
    assert "tool_1" in tool_names
    assert "tool_2" in tool_names


def test_get_trajectories_by_human_input(setup_db, sample_human_input):
    """Test retrieving trajectories by human input ID."""
    # Set up repository
    repo = TrajectoryRepository(db=setup_db)
    
    # Create another human input
    other_human_input = HumanInput.create(
        content="Another human input",
        source="test"
    )
    
    # Create trajectories for both human inputs
    for i in range(2):
        repo.create(
            tool_name=f"tool_1_{i}",
            human_input_id=sample_human_input.id
        )
    
    for i in range(3):
        repo.create(
            tool_name=f"tool_2_{i}",
            human_input_id=other_human_input.id
        )
    
    # Get trajectories for the first human input
    trajectories = repo.get_trajectories_by_human_input(sample_human_input.id)
    
    # Verify we got a list of TrajectoryModel objects for the first human input
    assert len(trajectories) == 2
    for trajectory in trajectories:
        assert isinstance(trajectory, TrajectoryModel)
        assert trajectory.human_input_id == sample_human_input.id
        assert trajectory.tool_name.startswith("tool_1")
    
    # Get trajectories for the second human input
    trajectories = repo.get_trajectories_by_human_input(other_human_input.id)
    
    # Verify we got a list of TrajectoryModel objects for the second human input
    assert len(trajectories) == 3
    for trajectory in trajectories:
        assert isinstance(trajectory, TrajectoryModel)
        assert trajectory.human_input_id == other_human_input.id
        assert trajectory.tool_name.startswith("tool_2")


def test_get_parsed_trajectory(setup_db, sample_trajectory, test_tool_parameters, test_tool_result, test_step_data):
    """Test retrieving a parsed trajectory."""
    # Set up repository
    repo = TrajectoryRepository(db=setup_db)
    
    # Get the parsed trajectory
    trajectory = repo.get_parsed_trajectory(sample_trajectory.id)
    
    # Verify type is TrajectoryModel, not Trajectory
    assert isinstance(trajectory, TrajectoryModel)
    
    # Verify the retrieved trajectory matches the original
    assert trajectory.id == sample_trajectory.id
    assert trajectory.tool_name == sample_trajectory.tool_name
    
    # Verify the JSON fields are dictionaries, not strings
    assert isinstance(trajectory.tool_parameters, dict)
    assert isinstance(trajectory.tool_result, dict)
    assert isinstance(trajectory.step_data, dict)
    
    # Verify the content of JSON fields
    assert trajectory.tool_parameters == test_tool_parameters
    assert trajectory.tool_result == test_tool_result
    assert trajectory.step_data == test_step_data
    
    # Verify non-existent trajectory returns None
    non_existent_trajectory = repo.get_parsed_trajectory(999)
    assert non_existent_trajectory is None


def test_trajectory_repository_manager(setup_db, cleanup_repo):
    """Test the TrajectoryRepositoryManager context manager."""
    # Use the context manager to create a repository
    with TrajectoryRepositoryManager(setup_db) as repo:
        # Verify the repository was created correctly
        assert isinstance(repo, TrajectoryRepository)
        assert repo.db is setup_db
        
        # Create a trajectory and verify it's a TrajectoryModel
        tool_parameters = {"test": "manager"}
        trajectory = repo.create(
            tool_name="manager_test",
            tool_parameters=tool_parameters
        )
        assert isinstance(trajectory, TrajectoryModel)
        assert trajectory.tool_parameters["test"] == "manager"
        
        # Verify we can get the repository using get_trajectory_repository
        repo_from_var = get_trajectory_repository()
        assert repo_from_var is repo
    
    # Verify the repository was removed from the context var
    with pytest.raises(RuntimeError) as excinfo:
        get_trajectory_repository()
    
    assert "No TrajectoryRepository available" in str(excinfo.value)


def test_repository_init_without_db():
    """Test that TrajectoryRepository raises an error when initialized without a db parameter."""
    # Attempt to create a repository without a database connection
    with pytest.raises(ValueError) as excinfo:
        TrajectoryRepository(db=None)
    
    # Verify the correct error message
    assert "Database connection is required" in str(excinfo.value)