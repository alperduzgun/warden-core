"""
Priority-based execution tests.

Tests that frames are executed in correct priority order:
- critical → high → medium → low
- Parallel mode groups frames by priority
"""

import pytest

from warden.models.frame import (
    GLOBAL_FRAMES,
    get_frames_by_priority,
    get_frames_grouped_by_priority,
    get_execution_groups,
    get_priority_value
)
from warden.models.pipeline_config import (
    PipelineConfig,
    PipelineNode,
    PipelineEdge,
    Position,
    PipelineSettings
)


class TestPrioritySorting:
    """Test priority sorting functions."""

    def test_priority_values(self):
        """Test priority numeric values."""
        assert get_priority_value('critical') == 0  # Highest
        assert get_priority_value('high') == 1
        assert get_priority_value('medium') == 2
        assert get_priority_value('low') == 3  # Lowest

    def test_get_frames_by_priority(self):
        """Test frames are sorted by priority."""
        sorted_frames = get_frames_by_priority(GLOBAL_FRAMES)

        # Security (critical) should be first
        assert sorted_frames[0].id == 'security'
        assert sorted_frames[0].priority == 'critical'

        # Chaos (high) should be second
        assert sorted_frames[1].id == 'chaos'
        assert sorted_frames[1].priority == 'high'

        # Stress (low) should be last
        assert sorted_frames[-1].id == 'stress'
        assert sorted_frames[-1].priority == 'low'

    def test_frames_grouped_by_priority(self):
        """Test frames are grouped correctly."""
        groups = get_frames_grouped_by_priority(GLOBAL_FRAMES)

        # Critical group has only security
        assert len(groups['critical']) == 1
        assert groups['critical'][0].id == 'security'

        # High group has only chaos
        assert len(groups['high']) == 1
        assert groups['high'][0].id == 'chaos'

        # Medium group has fuzz, property, architectural
        assert len(groups['medium']) == 3
        medium_ids = {f.id for f in groups['medium']}
        assert medium_ids == {'fuzz', 'property', 'architectural'}

        # Low group has only stress
        assert len(groups['low']) == 1
        assert groups['low'][0].id == 'stress'


class TestExecutionGroups:
    """Test execution group formation for parallel processing."""

    def test_execution_groups_order(self):
        """Test execution groups are in priority order."""
        groups = get_execution_groups(GLOBAL_FRAMES)

        # Should have 4 groups (critical, high, medium, low)
        assert len(groups) == 4

        # Group 1: critical
        assert len(groups[0]) == 1
        assert groups[0][0].id == 'security'

        # Group 2: high
        assert len(groups[1]) == 1
        assert groups[1][0].id == 'chaos'

        # Group 3: medium (can run in parallel)
        assert len(groups[2]) == 3
        medium_ids = {f.id for f in groups[2]}
        assert medium_ids == {'fuzz', 'property', 'architectural'}

        # Group 4: low
        assert len(groups[3]) == 1
        assert groups[3][0].id == 'stress'


class TestPipelineConfigPriority:
    """Test PipelineConfig priority-aware execution order."""

    def test_get_execution_order_with_priority(self):
        """Test execution order respects priority."""
        # Create simple pipeline with all 6 frames
        config = PipelineConfig(
            id='test-pipeline',
            name='Test Priority',
            nodes=[
                PipelineNode(id='start', type='start', position=Position(x=0, y=0), data={}),
                PipelineNode(id='frame-security', type='frame', position=Position(x=100, y=0),
                           data={'frameId': 'security'}),
                PipelineNode(id='frame-chaos', type='frame', position=Position(x=200, y=0),
                           data={'frameId': 'chaos'}),
                PipelineNode(id='frame-fuzz', type='frame', position=Position(x=300, y=0),
                           data={'frameId': 'fuzz'}),
                PipelineNode(id='frame-stress', type='frame', position=Position(x=400, y=0),
                           data={'frameId': 'stress'}),
                PipelineNode(id='end', type='end', position=Position(x=500, y=0), data={}),
            ],
            edges=[
                PipelineEdge(id='e1', source='start', target='frame-security'),
                PipelineEdge(id='e2', source='frame-security', target='frame-chaos'),
                PipelineEdge(id='e3', source='frame-chaos', target='frame-fuzz'),
                PipelineEdge(id='e4', source='frame-fuzz', target='frame-stress'),
                PipelineEdge(id='e5', source='frame-stress', target='end'),
            ]
        )

        order = config.get_execution_order(respect_priority=True)

        # Should be sorted by priority: security, chaos, fuzz, stress
        assert order[0] == 'frame-security'  # critical
        assert order[1] == 'frame-chaos'     # high
        assert order[2] == 'frame-fuzz'      # medium
        assert order[3] == 'frame-stress'    # low

    def test_get_execution_groups_for_parallel(self):
        """Test parallel execution groups."""
        config = PipelineConfig(
            id='test-pipeline',
            name='Test Parallel',
            nodes=[
                PipelineNode(id='start', type='start', position=Position(x=0, y=0), data={}),
                PipelineNode(id='frame-security', type='frame', position=Position(x=100, y=0),
                           data={'frameId': 'security'}),
                PipelineNode(id='frame-chaos', type='frame', position=Position(x=200, y=0),
                           data={'frameId': 'chaos'}),
                PipelineNode(id='frame-fuzz', type='frame', position=Position(x=300, y=0),
                           data={'frameId': 'fuzz'}),
                PipelineNode(id='frame-property', type='frame', position=Position(x=300, y=100),
                           data={'frameId': 'property'}),
                PipelineNode(id='end', type='end', position=Position(x=500, y=0), data={}),
            ],
            edges=[
                PipelineEdge(id='e1', source='start', target='frame-security'),
                PipelineEdge(id='e2', source='frame-security', target='frame-chaos'),
                PipelineEdge(id='e3', source='frame-chaos', target='frame-fuzz'),
                PipelineEdge(id='e4', source='frame-chaos', target='frame-property'),
                PipelineEdge(id='e5', source='frame-fuzz', target='end'),
                PipelineEdge(id='e6', source='frame-property', target='end'),
            ]
        )

        groups = config.get_execution_groups_for_parallel()

        # Should have 3 groups: critical, high, medium
        assert len(groups) >= 3

        # First group: security (critical)
        assert 'frame-security' in groups[0]

        # Second group: chaos (high)
        assert 'frame-chaos' in groups[1]

        # Third group: fuzz, property (medium) - can run in parallel
        assert 'frame-fuzz' in groups[2] or 'frame-property' in groups[2]


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
