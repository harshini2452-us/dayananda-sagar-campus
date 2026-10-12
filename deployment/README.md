# Dayananda Sagar Campus — AWS Lab

Architecture: HTTPS browser → Caddy/Gunicorn/Flask on EC2 → private RDS MySQL and private S3. SNS accepts a generic reminder digest; a systemd timer checks reminders at 09:00 India time.

`campus-stack.json` creates a disposable lab deployment. It does not retain the database, snapshots, secrets or S3 bucket on deletion. Keep the original local project and database as your source of truth.

1. Create a CloudFormation stack from this template in Stockholm (`eu-north-1`). Keep rollback enabled. A role with access to this deployment's resources is created.
2. While RDS creates, open the Files resource's private bucket. Upload the release archive as `deployment/campus-release.zip`.
3. The server installs the archive automatically after provisioning. Open the Website output once installation completes. The temporary hostname uses sslip.io; Caddy obtains a trusted certificate and redirects HTTP to HTTPS.
4. Retrieve the initial portal password from the PortalLoginSecret output in Secrets Manager. Cloud passwords are generated; local passwords remain unchanged. Accounts include ADMIN001, FAC001 through FAC010, and student USNs.
5. Use Admin → Campus Services → Fees to create charges or record already-received payments. Student → Fees shows balances and receipts. Student → Notifications shows reminders. The amounts are fictional lab records, and the app does not collect money.
6. Admin → Notification automation runs reminders immediately. SNS email requires a separately chosen and confirmed email subscription; publishing to a topic alone does not deliver email. Recovery/OTP email requires SMTP environment variables.
7. After the demo, empty this deployment's S3 bucket, delete the stack without retaining resources, and remove only its uploaded CloudFormation template objects. Verify EC2, RDS, EBS, EIP, S3, SNS and secrets are gone. Merely stopping instances does not stop all storage/IP charges.

The initial CloudFront attempt was blocked by AWS account verification, so this template uses direct HTTPS and no CloudFront distribution. No CloudShell or embedded AWS access keys are needed. EC2 uses its instance role.

Before future deployment, check the account plan, credits and current regional pricing. Keep this a brief lab run; do not upgrade the account plan without a separate decision.
