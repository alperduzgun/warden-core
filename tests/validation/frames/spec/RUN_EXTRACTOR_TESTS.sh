#!/bin/bash
# Quick reference script for running platform extractor tests
# Usage: bash RUN_EXTRACTOR_TESTS.sh [test_type]

set -e

echo "=========================================="
echo "Platform Extractor Tests - Quick Runner"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to run tests
run_test() {
    local test_file=$1
    local description=$2

    echo -e "${BLUE}Running: ${description}${NC}"
    echo "File: ${test_file}"
    echo "---"

    if python3 -m pytest "${test_file}" -v --tb=short; then
        echo -e "${GREEN}✓ ${description} PASSED${NC}"
    else
        echo -e "${YELLOW}✗ ${description} FAILED${NC}"
        return 1
    fi

    echo ""
}

# Check if pytest is available
if ! python3 -m pytest --version > /dev/null 2>&1; then
    echo -e "${YELLOW}Warning: pytest not installed${NC}"
    echo "Install with: pip install pytest pytest-asyncio"
    echo ""
fi

# Determine what to run
TEST_TYPE=${1:-all}

case "$TEST_TYPE" in
    flutter)
        echo "Running Flutter extractor tests only..."
        run_test "tests/validation/frames/spec/test_flutter_extractor.py" "Flutter Extractor Tests"
        ;;

    spring)
        echo "Running Spring Boot extractor tests only..."
        run_test "tests/validation/frames/spec/test_spring_extractor.py" "Spring Boot Extractor Tests"
        ;;

    integration)
        echo "Running integration tests only..."
        run_test "tests/validation/frames/spec/test_platform_integration.py" "Integration Tests"
        ;;

    all)
        echo "Running all platform extractor tests..."
        echo ""

        run_test "tests/validation/frames/spec/test_flutter_extractor.py" "Flutter Extractor Tests"
        run_test "tests/validation/frames/spec/test_spring_extractor.py" "Spring Boot Extractor Tests"
        run_test "tests/validation/frames/spec/test_platform_integration.py" "Integration Tests"

        echo "=========================================="
        echo -e "${GREEN}All tests completed!${NC}"
        echo "=========================================="
        ;;

    coverage)
        echo "Running tests with coverage report..."
        python3 -m pytest tests/validation/frames/spec/ \
            --cov=src/warden/validation/frames/spec/extractors \
            --cov-report=term-missing \
            --cov-report=html \
            -v

        echo ""
        echo -e "${GREEN}Coverage report generated in htmlcov/index.html${NC}"
        ;;

    quick)
        echo "Running quick smoke tests (empty project tests)..."
        python3 -m pytest \
            tests/validation/frames/spec/test_flutter_extractor.py::TestFlutterExtractor::test_empty_project \
            tests/validation/frames/spec/test_spring_extractor.py::TestSpringBootExtractor::test_empty_project \
            tests/validation/frames/spec/test_platform_integration.py::TestPlatformIntegration::test_compare_empty_projects \
            -v
        ;;

    *)
        echo "Unknown test type: $TEST_TYPE"
        echo ""
        echo "Usage: $0 [test_type]"
        echo ""
        echo "Available test types:"
        echo "  all          - Run all tests (default)"
        echo "  flutter      - Run Flutter extractor tests only"
        echo "  spring       - Run Spring Boot extractor tests only"
        echo "  integration  - Run integration tests only"
        echo "  coverage     - Run all tests with coverage report"
        echo "  quick        - Run quick smoke tests"
        echo ""
        echo "Examples:"
        echo "  $0                  # Run all tests"
        echo "  $0 flutter          # Run Flutter tests"
        echo "  $0 coverage         # Run with coverage"
        echo "  $0 quick            # Quick smoke test"
        exit 1
        ;;
esac

echo ""
echo "Done!"
