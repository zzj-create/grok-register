import unittest

from backend.mailbox.utilities import extract_verification_code


class ExtractVerificationCodeTests(unittest.TestCase):
    def test_pure_numeric_code_with_context_is_accepted(self):
        self.assertEqual(
            extract_verification_code(
                "Please use the code below to validate your email address.\r\n\r\n393-696",
                "SpaceXAI confirmation code: 393-696",
            ),
            "393-696",
        )

    def test_chinese_context_numeric_code_is_accepted(self):
        self.assertEqual(
            extract_verification_code("您的验证码：393-696，10 分钟内有效", "验证码"),
            "393-696",
        )

    def test_alphanumeric_code_still_works(self):
        self.assertEqual(
            extract_verification_code("Your code is G5T-CEO", "SpaceXAI confirmation code: G5T-CEO"),
            "G5T-CEO",
        )

    def test_bare_numeric_token_is_rejected(self):
        self.assertIsNone(
            extract_verification_code("width 100-200 and height 393-696 in styles", "布局说明")
        )

    def test_css_class_noise_is_rejected(self):
        self.assertIsNone(
            extract_verification_code("sm-w-per-100 sm-w-full class names", "Updates to our terms")
        )


if __name__ == "__main__":
    unittest.main()