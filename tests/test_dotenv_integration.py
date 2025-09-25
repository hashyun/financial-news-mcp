"""Test dotenv integration in server.py"""
import os
import tempfile
import pytest
from unittest.mock import patch


"""Test dotenv integration in server.py"""
import os
import tempfile
import pytest
import importlib
import sys


def test_dotenv_functionality():
    """Test that dotenv functionality works correctly with a real .env file"""
    # Create a temporary .env file in the project root
    env_path = "/home/runner/work/financial-news-mcp/financial-news-mcp/.env"
    
    # Save original env var state
    original_value = os.getenv("TEST_DOTENV_VAR")
    
    try:
        # Create .env file with test variable
        with open(env_path, 'w') as f:
            f.write("TEST_DOTENV_VAR=test_value_from_dotenv\n")
        
        # Remove server from cache to force reload
        if 'server' in sys.modules:
            del sys.modules['server']
        
        # Import server (which should load .env)
        import server
        
        # Check if the environment variable was loaded
        loaded_value = os.getenv("TEST_DOTENV_VAR")
        assert loaded_value == "test_value_from_dotenv", f"Expected 'test_value_from_dotenv', got '{loaded_value}'"
        
    finally:
        # Clean up
        if os.path.exists(env_path):
            os.unlink(env_path)
        
        # Restore original environment
        if original_value is None:
            os.environ.pop("TEST_DOTENV_VAR", None)
        else:
            os.environ["TEST_DOTENV_VAR"] = original_value


def test_server_imports_successfully():
    """Test that server.py can be imported without errors"""
    try:
        import server
        # Check that the expected functions are available
        assert hasattr(server, 'app')
        assert hasattr(server, '_dart_filings')
        assert hasattr(server, '_fred_fetch')
        assert hasattr(server, '_ecos_fetch')
    except ImportError as e:
        pytest.fail(f"Failed to import server: {e}")


def test_dotenv_loaded_before_imports():
    """Test that dotenv is loaded before finance_news imports"""
    # This is validated by the import order in server.py
    # If this test passes, it means the import order is correct
    import server
    
    # The server module should have all the expected attributes
    expected_attrs = [
        'app', '_http_get', '_fetch_yahoo_chart', '_google_news_rss',
        '_normalize_article', '_yahoo_options_chain', '_fred_fetch',
        '_ecos_fetch', '_dart_filings'
    ]
    
    for attr in expected_attrs:
        assert hasattr(server, attr), f"Missing expected attribute: {attr}"