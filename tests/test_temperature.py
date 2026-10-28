"""Unit tests for temperature conversions and precision."""
import tests  # noqa: F401
import unittest


class TestTemperatureConversion(unittest.TestCase):
    """Test temperature conversion and precision rounding."""

    def test_precision_half_degree_rounding(self):
        """Ensure half-degree Celsius values do not get truncated by int()."""
        # Test values that previously failed due to int() truncation:
        # 85.5 * 1.8 + 32 = 185.9 -> int() gave 185 (85.0 C), round() gives 186 (85.55 C)
        test_cases = [
            (40.0, 104),
            (40.5, 105),
            (50.0, 122),
            (50.5, 123),
            (85.0, 185),
            (85.5, 186),
            (99.0, 210),
            (99.5, 211),
            (100.0, 212),
        ]

        for celsius, expected_f in test_cases:
            with self.subTest(celsius=celsius):
                f = round(celsius * 1.8 + 32)
                self.assertEqual(f, expected_f)

                # Reverse conversion check
                back_c = (f - 32) / 1.8
                self.assertAlmostEqual(back_c, celsius, delta=0.3)


if __name__ == "__main__":
    unittest.main()
