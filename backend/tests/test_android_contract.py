from datetime import timedelta
from auth_fixtures import Fixture
import test_postgres as accounting

class AndroidLifetimeTests(Fixture):
    def test_login_reports_server_relative_monotonic_lifetime(self):
        from auth_fixtures import PASSWORD
        result=self.auth.login('client_fixture',PASSWORD,'127.0.0.1')
        self.assertEqual(result['expires_in_seconds'],28800)
        self.assertIs(type(result['expires_in_seconds']),int)

    def test_qr_lifetime_is_bounded_by_session_end(self):
        booking=self.store.book(self.client,self.subscription,'pool',accounting.START,45,'android_lifetime')['booking_id']
        self.now=accounting.START+timedelta(minutes=44,seconds=50)
        result=self.store.issue_qr(self.client,booking)
        self.assertEqual(result['valid_for_seconds'],10)
        self.assertIs(type(result['valid_for_seconds']),int)
