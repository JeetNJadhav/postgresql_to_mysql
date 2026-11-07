import uuid
import unittest
from product_migration.utils import uuid_bytes, category_id, related_id, product_slug

class UtilityTests(unittest.TestCase):
    def test_uuid_binary_is_canonical_order(self):
        value = "00112233-4455-6677-8899-aabbccddeeff"
        self.assertEqual(uuid_bytes(value), bytes.fromhex("00112233445566778899aabbccddeeff"))

    def test_deterministic_ids(self):
        self.assertEqual(category_id("Dairy"), category_id(" dairy "))
        self.assertEqual(related_id("x", "image", 0), related_id("x", "image", 0))
        self.assertEqual(uuid.UUID(bytes=category_id("Dairy")).version, 5)

    def test_slug(self):
        self.assertEqual(product_slug("Amul Taaza 1L"), "amul-taaza-1l")

    def test_bad_uuid_rejected(self):
        with self.assertRaises(ValueError):
            uuid_bytes("not-a-uuid")

if __name__ == "__main__":
    unittest.main()
