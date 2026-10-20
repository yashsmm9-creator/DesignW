"""Smoke tests for EduAdapt routes. Run with: python -m unittest discover -s tests"""
import os
import tempfile
import unittest

import app as edu


class EduAdaptSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db = edu.DB
        edu.DB = os.path.join(self.tempdir.name, 'test.db')
        edu.app.config.update(TESTING=True, SECRET_KEY='test-secret-key')
        edu.init_db()
        self.client = edu.app.test_client()

    def tearDown(self):
        edu.DB = self.old_db
        self.tempdir.cleanup()

    def register_and_login(self):
        response = self.client.post('/register', data={
            'name': 'Test Student', 'email': 'student@example.com',
            'password': 'StrongPass1!', 'confirm': 'StrongPass1!', 'phone': '+919876543210'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        import re
        match = re.search(rb'Local development code: <b>([0-9]{6})</b>', response.data)
        self.assertIsNotNone(match, response.data[:1200])
        c = edu.get_db()
        self.assertIsNone(c.execute('SELECT id FROM users WHERE email=?', ('student@example.com',)).fetchone())
        c.close()
        response = self.client.post('/register', data={
            'stage': 'verify_email_otp', 'otp': match.group(1).decode()
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        c = edu.get_db()
        self.assertIsNotNone(c.execute('SELECT id FROM users WHERE email=?', ('student@example.com',)).fetchone())
        c.close()
        response = self.client.post('/login', data={
            'email': 'student@example.com', 'password': 'StrongPass1!'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_private_pages_redirect_when_logged_out(self):
        self.assertIn(self.client.get('/dashboard').status_code, (302, 401))
        self.assertIn(self.client.get('/notes').status_code, (302, 401))

    def test_registration_login_notes_and_bookmarks(self):
        self.register_and_login()
        response = self.client.get('/notes')
        self.assertEqual(response.status_code, 200)
        c = edu.get_db()
        topic = c.execute('SELECT id FROM topics ORDER BY id LIMIT 1').fetchone()['id']
        c.close()
        self.assertEqual(self.client.get(f'/notes/{topic}').status_code, 200)
        self.assertEqual(self.client.post(f'/notes/{topic}/bookmark', follow_redirects=True).status_code, 200)
        self.assertEqual(self.client.get('/bookmarks').status_code, 200)
        self.assertEqual(self.client.post(f'/notes/{topic}/complete', follow_redirects=True).status_code, 200)

    def test_topic_quiz_submission_persists_result(self):
        self.register_and_login()
        c = edu.get_db()
        topic = c.execute('SELECT id FROM topics ORDER BY id LIMIT 1').fetchone()['id']
        questions = c.execute('SELECT id,correct FROM questions WHERE topic_id=? ORDER BY id', (topic,)).fetchall()
        c.close()
        self.assertGreaterEqual(len(questions), 10)
        data = {'started_at': '1'}
        for q in questions:
            data['q_' + str(q['id'])] = q['correct']
        response = self.client.post(f'/test/{topic}', data=data, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Result', response.data)


    def test_daily_target_alarm_api_and_completion(self):
        self.register_and_login()
        from datetime import date
        response = self.client.post('/targets', data={
            'title': 'Finish math practice', 'subject_id': '',
            'deadline': date.today().isoformat(), 'daily_minutes': '45',
            'daily_reminder_time': '18:30'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        rows = self.client.get('/api/daily-targets').get_json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['daily_reminder_time'], '18:30')
        self.assertEqual(rows[0]['completed_today'], 0)
        response = self.client.post(f"/targets/{rows[0]['id']}/complete-today")
        self.assertEqual(response.status_code, 200)
        rows = self.client.get('/api/daily-targets').get_json()
        self.assertEqual(rows[0]['completed_today'], 1)


if __name__ == '__main__':
    unittest.main()
