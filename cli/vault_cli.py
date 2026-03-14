#!/usr/bin/env python3
"""
trustMeBro-ARK Escrow CLI

Command-line interface for managing escrow deals via the REST API.

Commands:
    create        - Create a new deal
    status        - Check deal status
    list          - List deals (admin)
    fund          - Show funding invoice with QR code
    fund-wallet   - Fund from server wallet (admin/testnet)
    ship          - Mark deal as shipped (seller)
    release       - Release funds to seller (buyer confirms)
    refund        - Request refund (dispute + refund)
    dispute       - Open a dispute
    cancel-dispute - Cancel an open dispute
    system-status - Show system status
"""
import sys
import os
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime

import click
import requests

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_API_URL = os.getenv('ESCROW_API_URL', 'http://localhost:8001')
ADMIN_API_KEY = os.getenv('ADMIN_API_KEY', '')

# Local state for tracking deals we've interacted with
STATE_FILE = project_root / 'data' / 'cli_state.json'


def get_api_url():
    """Get API URL from env or default."""
    return os.getenv('ESCROW_API_URL', DEFAULT_API_URL)


def load_state():
    """Load CLI state (tracked deals, keys)."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text('{"deals": {}, "keys": {}}')
    return json.loads(STATE_FILE.read_text())


def save_state(state):
    """Save CLI state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ============================================================================
# API Helper
# ============================================================================

def normalize_deal(d):
    """Normalize API response field names for deals."""
    if not isinstance(d, dict):
        return d
    # Map API field names to CLI-friendly names
    if 'deal_id' in d and 'id' not in d:
        d['id'] = d['deal_id']
    if 'deal_link_token' in d and 'share_token' not in d:
        d['share_token'] = d['deal_link_token']
    return d


def api(method, endpoint, data=None, admin=False):
    """Make API request. Returns dict or raises."""
    url = f"{get_api_url()}{endpoint}"
    headers = {'Content-Type': 'application/json'}
    if admin and ADMIN_API_KEY:
        headers['X-Admin-Key'] = ADMIN_API_KEY

    try:
        if method == 'get':
            resp = requests.get(url, headers=headers, timeout=30)
        elif method == 'post':
            resp = requests.post(url, json=data, headers=headers, timeout=30)
        elif method == 'put':
            resp = requests.put(url, json=data, headers=headers, timeout=30)
        elif method == 'delete':
            resp = requests.delete(url, headers=headers, timeout=30)
        else:
            raise ValueError(f"Unknown method: {method}")

        if not resp.ok:
            detail = resp.json().get('detail', resp.text) if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            raise click.ClickException(f"API error ({resp.status_code}): {detail}")

        result = resp.json()
        # Auto-normalize deal responses
        if isinstance(result, dict):
            result = normalize_deal(result)
        return result
    except requests.ConnectionError:
        raise click.ClickException(f"Cannot connect to {get_api_url()} - is the backend running?")
    except requests.Timeout:
        raise click.ClickException("Request timed out")


# ============================================================================
# Signing Helper
# ============================================================================

def sign_action(private_key_hex, action, deal_id, timestamp):
    """Sign an action with coincurve."""
    try:
        from coincurve import PrivateKey
    except ImportError:
        raise click.ClickException("coincurve not installed: pip install coincurve")

    message = f"{action}:{deal_id}:{timestamp}"
    msg_hash = hashlib.sha256(message.encode()).digest()
    privkey = PrivateKey(bytes.fromhex(private_key_hex))
    sig = privkey.sign(msg_hash, hasher=None)
    return sig.hex()


def get_or_create_key(deal_id, role):
    """Get existing ephemeral key or create a new one for a deal."""
    state = load_state()
    key_id = f"{deal_id}:{role}"

    if key_id in state.get('keys', {}):
        return state['keys'][key_id]

    # Generate new key
    try:
        from coincurve import PrivateKey
    except ImportError:
        raise click.ClickException("coincurve not installed: pip install coincurve")

    privkey = PrivateKey()
    key_data = {
        'private_key': privkey.secret.hex(),
        'public_key': privkey.public_key.format().hex(),
        'role': role,
        'deal_id': deal_id,
    }

    state.setdefault('keys', {})[key_id] = key_data
    save_state(state)
    return key_data


# ============================================================================
# Display Helpers
# ============================================================================

def print_qr(data: str):
    """Print QR code to terminal."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1,
        )
        qr.add_data(data)
        qr.make(fit=True)

        matrix = qr.get_matrix()
        for row in matrix:
            line = '  '
            for cell in row:
                line += '██' if cell else '  '
            click.echo(line)
    except ImportError:
        click.echo("  (install qrcode: pip install qrcode)")
    except Exception as e:
        click.echo(f"  (QR code failed: {e})")


def format_sats(sats) -> str:
    """Format satoshis."""
    if sats is None:
        return "N/A"
    return f"{int(sats):,} sats"


def format_status(status: str) -> str:
    """Color-code status."""
    colors = {
        'pending': 'yellow',
        'active': 'cyan',
        'funded': 'green',
        'shipped': 'blue',
        'completed': 'green',
        'disputed': 'red',
        'refunded': 'magenta',
        'cancelled': 'red',
        'expired': 'red',
    }
    color = colors.get(status, 'white')
    return click.style(status.upper(), fg=color, bold=True)


def print_header(title: str):
    """Print styled header."""
    click.echo()
    click.echo(click.style('=' * 55, fg='blue'))
    click.echo(click.style(f'  {title}', fg='blue', bold=True))
    click.echo(click.style('=' * 55, fg='blue'))


def print_deal(deal, verbose=False):
    """Print deal details."""
    click.echo(f"\n  ID:          {click.style(deal['id'], fg='cyan')}")
    click.echo(f"  Status:      {format_status(deal['status'])}")
    click.echo(f"  Title:       {deal.get('title', 'N/A')}")
    click.echo(f"  Amount:      {format_sats(deal.get('price_sats'))}")

    if deal.get('description'):
        click.echo(f"  Description: {deal['description'][:60]}")

    click.echo(f"  Created:     {deal.get('created_at', 'N/A')}")

    if deal.get('share_token'):
        click.echo(f"  Share Token: {deal['share_token']}")

    if deal.get('seller_pubkey'):
        click.echo(f"  Seller:      {deal['seller_pubkey'][:16]}...")
    if deal.get('buyer_linking_pubkey'):
        click.echo(f"  Buyer:       {deal['buyer_linking_pubkey'][:16]}...")

    if deal.get('funded_at'):
        click.echo(f"  Funded:      {deal['funded_at']}")
    if deal.get('shipped_at'):
        click.echo(f"  Shipped:     {deal['shipped_at']}")
    if deal.get('completed_at'):
        click.echo(f"  Completed:   {deal['completed_at']}")
    if deal.get('disputed_at'):
        click.echo(f"  Disputed:    {deal['disputed_at']}")
        click.echo(f"  Dispute by:  {deal.get('disputed_by', 'N/A')}")
        click.echo(f"  Reason:      {deal.get('dispute_reason', 'N/A')}")
    if deal.get('refunded_at'):
        click.echo(f"  Refunded:    {deal['refunded_at']}")

    if verbose:
        if deal.get('ark_escrow_deal_id'):
            click.echo(f"  Escrow ID:  {deal['ark_escrow_deal_id']}")
        if deal.get('funding_address'):
            click.echo(f"  Fund Addr:   {deal['funding_address']}")

    # Suggest next action
    status = deal['status']
    deal_id = deal['id']
    click.echo()
    if status == 'pending':
        click.echo(click.style('  Next:', fg='yellow'))
        click.echo(f"    Share link with buyer: {get_api_url().replace(':8001',':5173')}/join/{deal.get('share_token','...')}")
    elif status == 'active':
        click.echo(click.style('  Next:', fg='yellow'))
        click.echo(f"    escrow-cli fund {deal_id}")
    elif status == 'funded':
        click.echo(click.style('  Next:', fg='yellow'))
        click.echo(f"    escrow-cli ship {deal_id}    (seller marks shipped)")
        click.echo(f"    escrow-cli release {deal_id}  (buyer releases funds)")
        click.echo(f"    escrow-cli dispute {deal_id}  (open dispute)")
    elif status == 'shipped':
        click.echo(click.style('  Next:', fg='yellow'))
        click.echo(f"    escrow-cli release {deal_id}  (buyer confirms delivery)")
        click.echo(f"    escrow-cli dispute {deal_id}  (open dispute)")
    elif status == 'disputed':
        click.echo(click.style('  Next:', fg='yellow'))
        click.echo(f"    escrow-cli cancel-dispute {deal_id}  (dispute opener cancels)")


# ============================================================================
# CLI Group
# ============================================================================

@click.group()
@click.option('--api-url', envvar='ESCROW_API_URL', default=None, help='API URL (default: http://localhost:8001)')
@click.version_option(version='3.0.0', prog_name='escrow-cli')
@click.pass_context
def cli(ctx, api_url):
    """
    trustMeBro-ARK Escrow CLI

    Manage deals via the REST API.
    Uses Lightning Network for payments and Ark for escrow.
    """
    if api_url:
        os.environ['ESCROW_API_URL'] = api_url


# ============================================================================
# SYSTEM-STATUS Command
# ============================================================================

@cli.command('system-status')
def system_status():
    """Show system status."""
    print_header('SYSTEM STATUS')

    # Health
    try:
        health = api('get', '/health')
        click.echo(f"\n  Backend: {click.style('online', fg='green')}")
    except Exception as e:
        click.echo(f"\n  Backend: {click.style('offline', fg='red')} ({e})")
        return

    # System status
    try:
        status = api('get', '/system-status')
        lnd = status.get('lnd', {})
        esplora = status.get('esplora', {})

        click.echo(click.style('\n  Lightning (LND):', bold=True))
        if lnd.get('available'):
            click.echo(f"    Status:  {click.style('online', fg='green')}")
            if lnd.get('alias'):
                click.echo(f"    Alias:   {lnd['alias']}")
            if lnd.get('balance_sats') is not None:
                click.echo(f"    Balance: {format_sats(lnd['balance_sats'])}")
        else:
            click.echo(f"    Status:  {click.style('offline', fg='red')}")

        click.echo(click.style('\n  Esplora:', bold=True))
        if esplora.get('available'):
            click.echo(f"    Status:  {click.style('online', fg='green')}")
            if esplora.get('block_height'):
                click.echo(f"    Block:   {esplora['block_height']}")
        else:
            click.echo(f"    Status:  {click.style('offline', fg='red')}")
    except Exception:
        pass

    # Limits
    try:
        limits = api('get', '/deals/settings/limits')
        click.echo(click.style('\n  Limits:', bold=True))
        click.echo(f"    Min: {format_sats(limits.get('min_sats'))}")
        click.echo(f"    Max: {format_sats(limits.get('max_sats'))}")
    except Exception:
        pass

    click.echo()


# ============================================================================
# CREATE Command
# ============================================================================

@cli.command()
@click.option('--amount', '-a', type=int, required=True, help='Price in satoshis')
@click.option('--title', '-t', required=True, help='Deal title')
@click.option('--description', '-d', default='', help='Deal description')
@click.option('--role', '-r', type=click.Choice(['seller', 'buyer']), default='seller', help='Your role')
def create(amount, title, description, role):
    """Create a new deal."""
    print_header('CREATE DEAL')

    click.echo(f"\n  Title:       {title}")
    click.echo(f"  Amount:      {format_sats(amount)}")
    click.echo(f"  Role:        {role}")
    if description:
        click.echo(f"  Description: {description}")

    # Generate a user ID for this CLI session
    user_id = f"cli_{role}_{os.urandom(4).hex()}"

    click.echo(click.style('\n  Creating deal...', fg='yellow'))

    data = {
        'title': title,
        'price_sats': amount,
        'description': description,
        'currency': 'BTC',
        'creator_role': role,
    }
    # Set the appropriate ID field based on role
    if role == 'seller':
        data['seller_id'] = user_id
    else:
        data['buyer_id'] = user_id

    deal = api('post', '/deals', data)

    deal_id = deal['id']
    token = deal.get('share_token', '')

    # Generate and register ephemeral key for our role
    key_data = get_or_create_key(deal_id, role)

    # Register via passphrase auth (no LNURL needed for CLI)
    try:
        api('post', '/auth/passphrase/register', {
            'deal_token': token,
            'role': role,
            'user_id': user_id,
            'ephemeral_pubkey': key_data['public_key'],
        })
        click.echo(click.style('  Key registered.', fg='green'))
    except Exception as e:
        click.echo(click.style(f'  Key registration failed: {e}', fg='yellow'))

    # Track deal locally
    state = load_state()
    state.setdefault('deals', {})[deal_id] = {
        'id': deal_id,
        'token': token,
        'role': role,
        'user_id': user_id,
        'title': title,
        'amount': amount,
        'created_at': datetime.now().isoformat(),
    }
    save_state(state)

    click.echo(click.style('\n  Deal created!', fg='green', bold=True))
    click.echo(f"\n  Deal ID:     {click.style(deal_id, fg='cyan', bold=True)}")
    click.echo(f"  Share Token: {click.style(token, fg='cyan')}")
    click.echo(f"  Status:      {format_status(deal['status'])}")

    frontend_url = get_api_url().replace(':8001', ':5173')
    click.echo(click.style('\n  Share with counterparty:', fg='yellow'))
    click.echo(f"    {frontend_url}/join/{token}")
    click.echo()
    click.echo(click.style('  Next steps:', fg='yellow'))
    click.echo(f"    escrow-cli status {deal_id}")
    click.echo(f"    escrow-cli fund {deal_id}")
    click.echo()


# ============================================================================
# JOIN Command
# ============================================================================

@cli.command()
@click.argument('token')
@click.option('--role', '-r', type=click.Choice(['buyer', 'seller']), default='buyer', help='Your role')
def join(token, role):
    """Join a deal using its share token."""
    print_header('JOIN DEAL')

    click.echo(f"\n  Token: {token}")
    click.echo(f"  Role:  {role}")

    # Get deal by token
    deal = api('get', f'/deals/token/{token}')
    deal_id = deal['id']

    click.echo(f"  Deal:  {click.style(deal_id, fg='cyan')}")
    click.echo(f"  Title: {deal.get('title', 'N/A')}")
    click.echo(f"  Price: {format_sats(deal.get('price_sats'))}")

    # Generate and register key
    key_data = get_or_create_key(deal_id, role)
    user_id = f"cli_{role}_{os.urandom(4).hex()}"

    try:
        api('post', '/auth/passphrase/register', {
            'deal_token': token,
            'role': role,
            'user_id': user_id,
            'ephemeral_pubkey': key_data['public_key'],
        })
        click.echo(click.style('\n  Joined deal!', fg='green', bold=True))
    except Exception as e:
        raise click.ClickException(f"Failed to join: {e}")

    # Track locally
    state = load_state()
    state.setdefault('deals', {})[deal_id] = {
        'id': deal_id,
        'token': token,
        'role': role,
        'user_id': user_id,
        'title': deal.get('title', ''),
        'amount': deal.get('price_sats'),
        'joined_at': datetime.now().isoformat(),
    }
    save_state(state)

    click.echo(f"  Status: {format_status(deal['status'])}")
    click.echo()
    click.echo(click.style('  Next:', fg='yellow'))
    click.echo(f"    escrow-cli status {deal_id}")
    click.echo(f"    escrow-cli fund {deal_id}")
    click.echo()


# ============================================================================
# STATUS Command
# ============================================================================

@cli.command()
@click.argument('deal_id')
@click.option('--verbose', '-v', is_flag=True, help='Show more details')
def status(deal_id, verbose):
    """Check deal status."""
    print_header('DEAL STATUS')

    deal = api('get', f'/deals/{deal_id}')
    print_deal(deal, verbose=verbose)

    # Show signing status if funded
    if deal['status'] in ('active', 'funded', 'shipped') and verbose:
        try:
            signing = api('get', f'/deals/{deal_id}/signing-status')
            click.echo(click.style('  Signing:', bold=True))
            click.echo(f"    Buyer signed:  {signing.get('buyer_signed', False)}")
            click.echo(f"    Seller signed: {signing.get('seller_signed', False)}")
        except Exception:
            pass

    click.echo()


# ============================================================================
# LIST Command
# ============================================================================

@cli.command('list')
@click.option('--all', '-a', 'include_finished', is_flag=True, help='Include completed/refunded')
@click.option('--admin', is_flag=True, help='List all deals (admin)')
@click.option('--limit', '-l', default=20, help='Max number of deals')
def list_deals(include_finished, admin, limit):
    """List deals."""
    print_header('DEAL LIST')

    if admin:
        deals_resp = api('get', f'/deals/admin/deals?include_finished={str(include_finished).lower()}&limit={limit}', admin=True)
        raw_deals = deals_resp if isinstance(deals_resp, list) else deals_resp.get('deals', [])
        deals = [normalize_deal(d) for d in raw_deals]
    else:
        # Show locally tracked deals
        state = load_state()
        local_deals = state.get('deals', {})
        if not local_deals:
            click.echo(click.style('\n  No deals tracked locally.', fg='yellow'))
            click.echo('  Create: escrow-cli create -a 50000 -t "Test Deal"')
            click.echo('  Or use: escrow-cli list --admin')
            click.echo()
            return

        deals = []
        for deal_id in local_deals:
            try:
                deal = api('get', f'/deals/{deal_id}')
                deals.append(deal)
            except Exception:
                deals.append({'id': deal_id, 'status': 'unknown', 'title': local_deals[deal_id].get('title', '?'), 'price_sats': local_deals[deal_id].get('amount')})

    if not deals:
        click.echo(click.style('\n  No deals found.', fg='yellow'))
        click.echo()
        return

    click.echo()
    click.echo(f"  {'ID':<38} {'STATUS':<12} {'AMOUNT':<14} {'TITLE'}")
    click.echo(f"  {'-'*38} {'-'*12} {'-'*14} {'-'*20}")

    for d in deals:
        did = d.get('id', '?')
        short_id = did[:36] + '..' if len(did) > 38 else did
        title = d.get('title', '?')[:20]
        click.echo(f"  {short_id:<38} {format_status(d.get('status','?')):<20} {format_sats(d.get('price_sats')):<14} {title}")

    click.echo()
    click.echo(f"  Total: {len(deals)}")
    click.echo()


# ============================================================================
# FUND Command
# ============================================================================

@cli.command()
@click.argument('deal_id')
@click.option('--no-qr', is_flag=True, help='Hide QR code')
@click.option('--poll', '-p', is_flag=True, help='Poll until paid')
def fund(deal_id, no_qr, poll):
    """Show or create funding invoice with QR code."""
    print_header('FUND DEAL')

    deal = api('get', f'/deals/{deal_id}')
    click.echo(f"\n  Deal:   {click.style(deal_id, fg='cyan')}")
    click.echo(f"  Title:  {deal.get('title', 'N/A')}")
    click.echo(f"  Amount: {format_sats(deal.get('price_sats'))}")
    click.echo(f"  Status: {format_status(deal['status'])}")

    if deal['status'] not in ('active', 'pending'):
        if deal['status'] == 'funded':
            click.echo(click.style('\n  Already funded!', fg='green'))
        else:
            click.echo(click.style(f"\n  Cannot fund in status: {deal['status']}", fg='red'))
        click.echo()
        return

    # Check for existing invoice first
    try:
        invoice_status = api('get', f'/deals/{deal_id}/check-ln-invoice')
        if invoice_status.get('invoice'):
            invoice = invoice_status['invoice']
            click.echo(click.style('\n  Existing invoice found.', fg='yellow'))
        else:
            raise Exception("No invoice")
    except Exception:
        # Create new invoice
        click.echo(click.style('\n  Creating invoice...', fg='yellow'))
        result = api('post', f'/deals/{deal_id}/create-ln-invoice')
        invoice = result.get('invoice', result.get('payment_request', ''))

    if not invoice:
        click.echo(click.style('\n  Error: No invoice returned', fg='red'))
        return

    click.echo(click.style('\n  Lightning Invoice:', fg='yellow', bold=True))
    click.echo()

    if not no_qr:
        print_qr(invoice.upper())
        click.echo()

    # Print full invoice for copy
    click.echo(click.style('  Invoice:', fg='white'))
    # Split long invoice into lines
    for i in range(0, len(invoice), 70):
        click.echo(f"  {invoice[i:i+70]}")

    click.echo()
    click.echo(click.style('  Pay with Lightning wallet, then:', fg='yellow'))
    click.echo(f"    escrow-cli status {deal_id}")

    if poll:
        click.echo(click.style('\n  Waiting for payment...', fg='yellow'))
        for i in range(120):
            time.sleep(5)
            try:
                check = api('get', f'/deals/{deal_id}/check-ln-invoice')
                if check.get('paid') or check.get('status') == 'paid':
                    click.echo(click.style('\n  PAID!', fg='green', bold=True))
                    break
            except Exception:
                pass
            if i % 6 == 0:
                click.echo(f"    ... waiting ({(i+1)*5}s)")
        else:
            click.echo(click.style('\n  Timed out waiting for payment.', fg='yellow'))

    click.echo()


# ============================================================================
# FUND-WALLET Command (Admin)
# ============================================================================

@cli.command('fund-wallet')
@click.argument('deal_id')
def fund_wallet(deal_id):
    """Fund deal from server wallet (admin/testnet)."""
    print_header('FUND FROM WALLET')

    deal = api('get', f'/deals/{deal_id}')
    click.echo(f"\n  Deal:   {click.style(deal_id, fg='cyan')}")
    click.echo(f"  Amount: {format_sats(deal.get('price_sats'))}")
    click.echo(f"  Status: {format_status(deal['status'])}")

    click.echo(click.style('\n  Funding from wallet...', fg='yellow'))
    result = api('post', f'/deals/admin/{deal_id}/fund-from-wallet', admin=True)

    click.echo(click.style('\n  Funded!', fg='green', bold=True))
    if result.get('txid'):
        click.echo(f"    TXID: {result['txid']}")
    click.echo()


# ============================================================================
# SHIP Command
# ============================================================================

@cli.command()
@click.argument('deal_id')
@click.option('--carrier', '-c', default='', help='Shipping carrier')
@click.option('--tracking', '-t', default='', help='Tracking number')
@click.option('--notes', '-n', default='', help='Shipping notes')
def ship(deal_id, carrier, tracking, notes):
    """Mark deal as shipped (seller)."""
    print_header('MARK AS SHIPPED')

    deal = api('get', f'/deals/{deal_id}')
    click.echo(f"\n  Deal:   {click.style(deal_id, fg='cyan')}")
    click.echo(f"  Status: {format_status(deal['status'])}")

    if deal['status'] != 'funded':
        raise click.ClickException(f"Deal must be funded to ship (is: {deal['status']})")

    # Get key for seller
    state = load_state()
    local = state.get('deals', {}).get(deal_id, {})
    key_id = f"{deal_id}:seller"
    key_data = state.get('keys', {}).get(key_id)

    if not key_data:
        raise click.ClickException("No seller key found. Did you create/join this deal as seller?")

    timestamp = int(time.time())
    signature = sign_action(key_data['private_key'], 'ship', deal_id, timestamp)

    # We need the seller user_id - get from signing status
    signing = api('get', f'/deals/{deal_id}/signing-status')
    seller_id = signing.get('seller_user_id') or deal.get('seller_user_id')
    if not seller_id:
        raise click.ClickException("Cannot determine seller user ID")

    data = {
        'seller_id': seller_id,
        'tracking_carrier': carrier or None,
        'tracking_number': tracking or None,
        'shipping_notes': notes or None,
        'signature': signature,
        'timestamp': timestamp,
    }

    result = api('post', f'/deals/{deal_id}/ship', data)
    click.echo(click.style('\n  Marked as shipped!', fg='green', bold=True))
    click.echo()


# ============================================================================
# RELEASE Command
# ============================================================================

@cli.command()
@click.argument('deal_id')
@click.option('--invoice', '-i', default=None, help='Seller Lightning invoice for payout')
@click.option('--dev', is_flag=True, help='Use dev-release (admin, skip signing)')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation')
def release(deal_id, invoice, dev, yes):
    """Release funds to seller."""
    print_header('RELEASE TO SELLER')

    deal = api('get', f'/deals/{deal_id}')
    click.echo(f"\n  Deal:   {click.style(deal_id, fg='cyan')}")
    click.echo(f"  Title:  {deal.get('title', 'N/A')}")
    click.echo(f"  Amount: {format_sats(deal.get('price_sats'))}")
    click.echo(f"  Status: {format_status(deal['status'])}")

    if dev:
        if not yes:
            click.echo(click.style('\n  This will release funds (dev mode)!', fg='yellow', bold=True))
            if not click.confirm('  Proceed?'):
                click.echo('  Cancelled.')
                return

        click.echo(click.style('\n  Dev-releasing...', fg='yellow'))
        result = api('post', f'/deals/admin/{deal_id}/dev-release', admin=True)
        click.echo(click.style('\n  Released (dev mode)!', fg='green', bold=True))
        click.echo()
        return

    if deal['status'] not in ('funded', 'shipped'):
        raise click.ClickException(f"Deal must be funded or shipped (is: {deal['status']})")

    # Get buyer key for signing the release
    key_id = f"{deal_id}:buyer"
    state = load_state()
    key_data = state.get('keys', {}).get(key_id)

    if not key_data:
        raise click.ClickException("No buyer key found. Did you join this deal as buyer?")

    if not yes:
        click.echo(click.style('\n  This releases funds to the seller!', fg='yellow', bold=True))
        if not click.confirm('  Proceed?'):
            click.echo('  Cancelled.')
            return

    # Step 1: Sign the release action
    timestamp = int(time.time())
    signature = sign_action(key_data['private_key'], 'release', deal_id, timestamp)

    signing = api('get', f'/deals/{deal_id}/signing-status')
    buyer_id = signing.get('buyer_user_id') or deal.get('buyer_user_id')
    if not buyer_id:
        raise click.ClickException("Cannot determine buyer user ID")

    click.echo(click.style('\n  Releasing...', fg='yellow'))
    result = api('post', f'/deals/{deal_id}/release', {
        'buyer_id': buyer_id,
        'signature': signature,
        'timestamp': timestamp,
    })

    click.echo(click.style('\n  Release initiated!', fg='green', bold=True))

    # Step 2: If seller needs to provide invoice for payout
    updated_deal = api('get', f'/deals/{deal_id}')
    if updated_deal['status'] == 'completed':
        click.echo('  Deal is completed.')
    elif invoice:
        click.echo('  Submitting payout invoice...')
        # The seller submits the invoice
        seller_key_id = f"{deal_id}:seller"
        seller_key = state.get('keys', {}).get(seller_key_id)
        if seller_key:
            ts2 = int(time.time())
            sig2 = sign_action(seller_key['private_key'], 'submit-payout-invoice', deal_id, ts2)
            seller_id = signing.get('seller_user_id') or deal.get('seller_user_id')
            api('post', f'/deals/{deal_id}/submit-payout-invoice', {
                'user_id': seller_id,
                'invoice': invoice,
                'signature': sig2,
                'timestamp': ts2,
            })
            click.echo(click.style('  Payout invoice submitted!', fg='green'))

    click.echo()


# ============================================================================
# REFUND Command
# ============================================================================

@cli.command()
@click.argument('deal_id')
@click.option('--invoice', '-i', default=None, help='Buyer Lightning invoice for refund')
@click.option('--reason', '-r', default='Requesting refund', help='Reason')
@click.option('--dev', is_flag=True, help='Use dev-refund (admin, skip signing)')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation')
def refund(deal_id, invoice, reason, dev, yes):
    """Request refund to buyer."""
    print_header('REFUND TO BUYER')

    deal = api('get', f'/deals/{deal_id}')
    click.echo(f"\n  Deal:   {click.style(deal_id, fg='cyan')}")
    click.echo(f"  Amount: {format_sats(deal.get('price_sats'))}")
    click.echo(f"  Status: {format_status(deal['status'])}")

    if dev:
        if not yes:
            click.echo(click.style('\n  This will refund (dev mode)!', fg='yellow', bold=True))
            if not click.confirm('  Proceed?'):
                click.echo('  Cancelled.')
                return

        click.echo(click.style('\n  Dev-refunding...', fg='yellow'))
        result = api('post', f'/deals/admin/{deal_id}/dev-refund', admin=True)
        click.echo(click.style('\n  Refunded (dev mode)!', fg='green', bold=True))
        click.echo()
        return

    if deal['status'] not in ('funded', 'shipped', 'disputed'):
        raise click.ClickException(f"Deal must be funded/shipped/disputed (is: {deal['status']})")

    if not yes:
        click.echo(click.style('\n  This initiates a refund!', fg='yellow', bold=True))
        if not click.confirm('  Proceed?'):
            click.echo('  Cancelled.')
            return

    # Admin resolve-refund path
    click.echo(click.style('\n  Resolving refund (admin)...', fg='yellow'))
    result = api('post', f'/deals/admin/{deal_id}/resolve-refund', {
        'resolution_note': reason,
    }, admin=True)

    click.echo(click.style('\n  Refund resolved!', fg='green', bold=True))

    # Submit refund invoice if provided
    if invoice:
        state = load_state()
        buyer_key_id = f"{deal_id}:buyer"
        buyer_key = state.get('keys', {}).get(buyer_key_id)
        if buyer_key:
            ts = int(time.time())
            sig = sign_action(buyer_key['private_key'], 'submit-refund-invoice', deal_id, ts)
            signing = api('get', f'/deals/{deal_id}/signing-status')
            buyer_id = signing.get('buyer_user_id') or deal.get('buyer_user_id')
            api('post', f'/deals/{deal_id}/submit-refund-invoice', {
                'user_id': buyer_id,
                'invoice': invoice,
                'signature': sig,
                'timestamp': ts,
            })
            click.echo(click.style('  Refund invoice submitted!', fg='green'))

    click.echo()


# ============================================================================
# DISPUTE Command
# ============================================================================

@cli.command()
@click.argument('deal_id')
@click.option('--reason', '-r', required=True, help='Dispute reason')
@click.option('--role', type=click.Choice(['buyer', 'seller']), required=True, help='Your role')
def dispute(deal_id, reason, role):
    """Open a dispute on a deal."""
    print_header('OPEN DISPUTE')

    deal = api('get', f'/deals/{deal_id}')
    click.echo(f"\n  Deal:   {click.style(deal_id, fg='cyan')}")
    click.echo(f"  Status: {format_status(deal['status'])}")

    if deal['status'] not in ('funded', 'shipped'):
        raise click.ClickException(f"Can only dispute funded/shipped deals (is: {deal['status']})")

    key_id = f"{deal_id}:{role}"
    state = load_state()
    key_data = state.get('keys', {}).get(key_id)

    if not key_data:
        raise click.ClickException(f"No {role} key found. Did you create/join as {role}?")

    signing = api('get', f'/deals/{deal_id}/signing-status')
    user_id = signing.get(f'{role}_user_id') or deal.get(f'{role}_user_id')
    if not user_id:
        raise click.ClickException(f"Cannot determine {role} user ID")

    timestamp = int(time.time())
    signature = sign_action(key_data['private_key'], 'dispute', deal_id, timestamp)

    result = api('post', f'/deals/{deal_id}/dispute', {
        'user_id': user_id,
        'reason': reason,
        'signature': signature,
        'timestamp': timestamp,
    })

    click.echo(click.style('\n  Dispute opened!', fg='yellow', bold=True))
    click.echo(f"  Reason: {reason}")
    click.echo()


# ============================================================================
# CANCEL-DISPUTE Command
# ============================================================================

@cli.command('cancel-dispute')
@click.argument('deal_id')
@click.option('--role', type=click.Choice(['buyer', 'seller']), required=True, help='Your role (must be dispute opener)')
def cancel_dispute(deal_id, role):
    """Cancel an open dispute (only opener can cancel)."""
    print_header('CANCEL DISPUTE')

    deal = api('get', f'/deals/{deal_id}')
    click.echo(f"\n  Deal:   {click.style(deal_id, fg='cyan')}")
    click.echo(f"  Status: {format_status(deal['status'])}")

    if deal['status'] != 'disputed':
        raise click.ClickException(f"Deal is not disputed (is: {deal['status']})")

    key_id = f"{deal_id}:{role}"
    state = load_state()
    key_data = state.get('keys', {}).get(key_id)

    if not key_data:
        raise click.ClickException(f"No {role} key found.")

    signing = api('get', f'/deals/{deal_id}/signing-status')
    user_id = signing.get(f'{role}_user_id') or deal.get(f'{role}_user_id')
    if not user_id:
        raise click.ClickException(f"Cannot determine {role} user ID")

    timestamp = int(time.time())
    signature = sign_action(key_data['private_key'], 'cancel-dispute', deal_id, timestamp)

    result = api('post', f'/deals/{deal_id}/cancel-dispute', {
        'user_id': user_id,
        'signature': signature,
        'timestamp': timestamp,
    })

    click.echo(click.style('\n  Dispute cancelled!', fg='green', bold=True))
    click.echo(f"  Deal returned to: {format_status(result.get('status', '?'))}")
    click.echo()


# ============================================================================
# ADMIN Commands
# ============================================================================

@cli.group('admin')
def admin_group():
    """Admin commands (require ADMIN_API_KEY)."""
    pass


@admin_group.command('disputes')
def admin_disputes():
    """List disputed deals."""
    print_header('DISPUTED DEALS')

    resp = api('get', '/deals/admin/disputes', admin=True)
    disputes = resp.get('deals', resp) if isinstance(resp, dict) else resp
    disputes = [normalize_deal(d) for d in disputes]
    if not disputes:
        click.echo(click.style('\n  No disputed deals.', fg='green'))
        click.echo()
        return

    for d in disputes:
        click.echo(f"\n  {click.style(d['id'], fg='cyan')}")
        click.echo(f"    Title:  {d.get('title', 'N/A')}")
        click.echo(f"    Amount: {format_sats(d.get('price_sats'))}")
        click.echo(f"    By:     {d.get('disputed_by', 'N/A')}")
        click.echo(f"    Reason: {d.get('dispute_reason', 'N/A')}")

    click.echo()


@admin_group.command('resolve-release')
@click.argument('deal_id')
@click.option('--note', '-n', default=None, help='Resolution note')
def admin_resolve_release(deal_id, note):
    """Resolve dispute by releasing to seller."""
    print_header('ADMIN: RESOLVE RELEASE')

    result = api('post', f'/deals/admin/{deal_id}/resolve-release', {
        'resolution_note': note,
    }, admin=True)

    click.echo(click.style('\n  Released!', fg='green', bold=True))
    click.echo()


@admin_group.command('resolve-refund')
@click.argument('deal_id')
@click.option('--note', '-n', default=None, help='Resolution note')
def admin_resolve_refund(deal_id, note):
    """Resolve dispute by refunding buyer."""
    print_header('ADMIN: RESOLVE REFUND')

    result = api('post', f'/deals/admin/{deal_id}/resolve-refund', {
        'resolution_note': note,
    }, admin=True)

    click.echo(click.style('\n  Refunded!', fg='green', bold=True))
    click.echo()


@admin_group.command('config')
def admin_config():
    """Show admin configuration."""
    print_header('ADMIN CONFIG')

    config = api('get', '/deals/admin/config', admin=True)

    click.echo()
    for key, value in config.items():
        click.echo(f"  {key}: {value}")
    click.echo()


# ============================================================================
# Entry Point
# ============================================================================

def main():
    cli()


if __name__ == '__main__':
    main()
