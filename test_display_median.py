import unittest

from display_median import DisplayMedianBuffer


class DisplayMedianBufferTests(unittest.TestCase):
    def test_returns_coordinate_wise_median_and_discards_outlier(self):
        buffer = DisplayMedianBuffer()
        for value in (10.0, 10.2, 250.0, 9.9, 10.1):
            buffer.add({
                "transversal": value,
                "coronal": value + 1.0,
                "sagittal": value + 2.0,
            })

        self.assertEqual(
            buffer.take_median(),
            {
                "transversal": 10.1,
                "coronal": 11.1,
                "sagittal": 12.1,
            },
        )

    def test_each_sample_is_used_in_only_one_window(self):
        buffer = DisplayMedianBuffer()
        buffer.add({"x": 1.0})

        self.assertEqual(buffer.take_median(), {"x": 1.0})
        self.assertIsNone(buffer.take_median())

        buffer.add({"x": 3.0})
        self.assertEqual(buffer.take_median(), {"x": 3.0})

    def test_even_sample_count_uses_middle_pair_mean(self):
        buffer = DisplayMedianBuffer()
        buffer.add({"x": 1.0})
        buffer.add({"x": 5.0})

        self.assertEqual(buffer.take_median(), {"x": 3.0})

    def test_rejects_non_finite_coordinates(self):
        buffer = DisplayMedianBuffer()

        with self.assertRaises(ValueError):
            buffer.add({"x": float("nan")})


if __name__ == "__main__":
    unittest.main()
