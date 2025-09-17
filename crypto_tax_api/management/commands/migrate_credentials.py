from django.core.management.base import BaseCommand
from crypto_tax_api.models import ExchangeCredential


class Command(BaseCommand):
    help = 'Migrate existing exchange credentials to enhanced encryption format'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without actually doing it'
        )

    def handle(self, *args, **options):
        credentials = ExchangeCredential.objects.all()

        self.stdout.write(f"Found {credentials.count()} exchange credentials to check")

        migrated_count = 0
        error_count = 0

        for cred in credentials:
            try:
                # Test if it needs migration by checking format
                decrypted = cred.get_decrypted_credentials()

                # Check if it's old format by trying to decrypt and see if timestamp is present
                from cryptography.fernet import Fernet
                from django.conf import settings

                fernet = Fernet(settings.ENCRYPTION_KEY)
                decrypted_key_data = fernet.decrypt(cred.api_key.encode()).decode()

                if ':' not in decrypted_key_data or not decrypted_key_data.split(':', 1)[0].isdigit():
                    # Old format, needs migration
                    if not options['dry_run']:
                        cred.migrate_to_enhanced_encryption()
                        migrated_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"Migrated credentials for exchange {cred.id} ({cred.exchange})")
                        )
                    else:
                        self.stdout.write(f"Would migrate: {cred.id} ({cred.exchange})")
                        migrated_count += 1
                else:
                    self.stdout.write(f"Already using new format: {cred.id} ({cred.exchange})")

            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f"Error processing {cred.id} ({cred.exchange}): {e}")
                )

        if options['dry_run']:
            self.stdout.write(f"Dry run complete. Would migrate {migrated_count} credentials, {error_count} errors")
        else:
            self.stdout.write(f"Migration complete. Migrated {migrated_count} credentials, {error_count} errors")
