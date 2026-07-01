import socket
from unittest.mock import MagicMock, mock_open, patch

from registration_engine import provider


@patch('registration_engine.provider.urllib.request.urlopen')
def test_check_imds_endpoint_success(mock_urlopen):
    """Test successful IMDS endpoint HTTP request."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'test_body'
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    success, body = provider.check_imds_endpoint('http://fake-url')

    assert success is True
    assert body == 'test_body'


@patch('registration_engine.provider.urllib.request.urlopen')
def test_check_imds_endpoint_timeout(mock_urlopen):
    """Test IMDS endpoint timeout handling."""
    mock_urlopen.side_effect = socket.timeout

    success, body = provider.check_imds_endpoint('http://fake-url')

    assert success is False
    assert body == ''


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_azure_imds_ipv4_success(mock_check):
    """Test Azure IMDS succeeding on the first (IPv4) attempt."""
    mock_check.side_effect = [(True, '')]

    assert provider.check_azure_imds() is True
    assert mock_check.call_count == 1


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_azure_imds_ipv6_fallback(mock_check):
    """Test Azure IMDS falling back to IPv4-mapped IPv6."""
    mock_check.side_effect = [(False, ''), (True, '')]

    assert provider.check_azure_imds() is True
    assert mock_check.call_count == 2


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_azure_imds_all_fail(mock_check):
    """Test Azure IMDS returning False when all attempts fail."""
    mock_check.side_effect = [(False, ''), (False, '')]

    assert provider.check_azure_imds() is False
    assert mock_check.call_count == 2


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_gcp_imds_dns_success(mock_check):
    """Test GCP IMDS succeeding on the DNS hostname."""
    mock_check.side_effect = [(True, '')]

    assert provider.check_gcp_imds() is True
    assert mock_check.call_count == 1


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_gcp_imds_ipv4_fallback(mock_check):
    """Test GCP IMDS falling back to IPv4 after DNS failure."""
    mock_check.side_effect = [(False, ''), (True, ''), (False, '')]

    assert provider.check_gcp_imds() is True
    assert mock_check.call_count == 2


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_gcp_imds_all_fail(mock_check):
    """Test GCP IMDS failing across DNS, IPv4, and IPv6."""
    mock_check.return_value = (False, '')

    assert provider.check_gcp_imds() is False
    assert mock_check.call_count == 3


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_aws_imds_ipv4_v2_success(mock_check):
    """Test AWS IMDSv2 success on first IPv4 attempt."""
    mock_check.side_effect = [(True, 'fake_token'), (True, '')]

    assert provider.check_aws_imds() is True
    assert mock_check.call_count == 2


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_aws_imds_ipv4_v1_fallback(mock_check):
    """Test AWS IMDS falling back to v1 on IPv4."""
    mock_check.side_effect = [(False, ''), (True, '')]

    assert provider.check_aws_imds() is True
    assert mock_check.call_count == 2


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_aws_imds_ipv6_v2_success(mock_check):
    """Test AWS IMDS falling back to IPv6 after complete IPv4 failure."""
    mock_check.side_effect = [
        (False, ''),       # IPv4 IMDSv2 PUT fails
        (False, ''),       # IPv4 IMDSv1 GET fails
        (True, 'token'),   # IPv6 IMDSv2 PUT succeeds
        (True, ''),        # IPv6 IMDSv2 GET succeeds
    ]

    assert provider.check_aws_imds() is True
    assert mock_check.call_count == 4


@patch(
    'builtins.open',
    new_callable=mock_open,
    read_data='Microsoft Corporation'
)
def test_check_dmi_files_azure(mock_file):
    """Test DMI file reading for Azure."""
    result = provider.check_dmi_files()
    assert result == provider.PROVIDER_MICROSOFT


@patch('builtins.open', new_callable=mock_open, read_data='Amazon EC2')
def test_check_dmi_files_aws(mock_file):
    """Test DMI file reading for AWS."""
    result = provider.check_dmi_files()
    assert result == provider.PROVIDER_AMAZON


@patch('builtins.open', side_effect=FileNotFoundError)
def test_check_dmi_files_not_found(mock_file):
    """Test DMI file missing."""
    assert provider.check_dmi_files() is None


@patch('registration_engine.provider.subprocess.run')
def test_check_dmidecode_gcp(mock_run):
    """Test dmidecode fallback for GCP."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b'Google'
    mock_run.return_value = mock_result

    assert provider.check_dmidecode() == provider.PROVIDER_GOOGLE


@patch('registration_engine.provider.subprocess.run')
def test_check_dmidecode_microsoft(mock_run):
    """Test dmidecode fallback for Microsoft."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b'Microsoft Corporation'
    mock_run.return_value = mock_result

    assert provider.check_dmidecode() == provider.PROVIDER_MICROSOFT


@patch('registration_engine.provider.subprocess.run')
def test_check_dmidecode_amazon(mock_run):
    """Test dmidecode fallback for Amazon."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b'Amazon EC2'
    mock_run.return_value = mock_result

    assert provider.check_dmidecode() == provider.PROVIDER_AMAZON


@patch('registration_engine.provider.subprocess.run')
def test_check_dmidecode_missing_binary(mock_run):
    """Test dmidecode check when binary is not installed."""
    mock_run.side_effect = FileNotFoundError

    assert provider.check_dmidecode() is None


@patch('registration_engine.provider.check_aws_imds', return_value=False)
@patch('registration_engine.provider.check_gcp_imds', return_value=False)
@patch('registration_engine.provider.check_azure_imds', return_value=True)
def test_detect_cloud_provider_imds_wins(mock_az, mock_gcp, mock_aws):
    """Test that IMDS successful detection short-circuits fallbacks."""
    result = provider.detect_cloud_provider()
    assert result == provider.PROVIDER_MICROSOFT


@patch('registration_engine.provider.check_aws_imds', return_value=False)
@patch('registration_engine.provider.check_gcp_imds', return_value=False)
@patch('registration_engine.provider.check_azure_imds', return_value=False)
@patch('registration_engine.provider.check_dmi_files', return_value='amazon')
def test_detect_cloud_provider_dmi_fallback(
    mock_dmi, mock_az, mock_gcp, mock_aws
):
    """Test fallback to DMI files when IMDS fails."""
    result = provider.detect_cloud_provider()
    assert result == provider.PROVIDER_AMAZON


@patch('registration_engine.provider.check_aws_imds', return_value=False)
@patch('registration_engine.provider.check_gcp_imds', return_value=False)
@patch('registration_engine.provider.check_azure_imds', return_value=False)
@patch('registration_engine.provider.check_dmi_files', return_value=None)
@patch('registration_engine.provider.check_dmidecode', return_value=None)
def test_detect_cloud_provider_unknown(
    mock_dmidecode, mock_dmi, mock_az, mock_gcp, mock_aws
):
    """Test that total failure returns the unknown constant."""
    result = provider.detect_cloud_provider()
    assert result == provider.PROVIDER_UNKNOWN


@patch('registration_engine.provider.check_aws_imds', return_value=False)
@patch('registration_engine.provider.check_gcp_imds', return_value=True)
@patch('registration_engine.provider.check_azure_imds', return_value=False)
def test_detect_cloud_provider_gcp_imds(mock_az, mock_gcp, mock_aws):
    """Test that Google Cloud Platform IMDS is detected and logged."""
    result = provider.detect_cloud_provider()
    assert result == provider.PROVIDER_GOOGLE


@patch('registration_engine.provider.check_aws_imds', return_value=True)
@patch('registration_engine.provider.check_gcp_imds', return_value=False)
@patch('registration_engine.provider.check_azure_imds', return_value=False)
def test_detect_cloud_provider_aws_imds(mock_az, mock_gcp, mock_aws):
    """Test that Amazon Web Services IMDS is detected and logged."""
    result = provider.detect_cloud_provider()
    assert result == provider.PROVIDER_AMAZON


@patch('registration_engine.provider.check_aws_imds', return_value=False)
@patch('registration_engine.provider.check_gcp_imds', return_value=False)
@patch('registration_engine.provider.check_azure_imds', return_value=False)
@patch('registration_engine.provider.check_dmi_files', return_value=None)
@patch(
    'registration_engine.provider.check_dmidecode',
    return_value='microsoft'
)
def test_detect_cloud_provider_dmidecode(
    mock_dmidecode, mock_dmi, mock_az, mock_gcp, mock_aws
):
    """Test that dmidecode success fallback is logged and returned."""
    result = provider.detect_cloud_provider()
    assert result == provider.PROVIDER_MICROSOFT


@patch(
    'registration_engine.provider.check_imds_endpoint',
    return_value=(False, '')
)
def test_check_aws_imds_all_fail(mock_check):
    """Test AWS IMDS returning False when all attempts fail."""
    assert provider.check_aws_imds() is False


@patch('builtins.open')
def test_check_dmi_files_amazon(mock_open_file):
    """Test reading amazon/ec2 content from DMI files."""
    mock_file = MagicMock()
    mock_file.read.return_value = "EC2 Amazon Web Services"
    mock_open_file.return_value.__enter__.return_value = mock_file
    assert provider.check_dmi_files() == provider.PROVIDER_AMAZON


@patch('builtins.open')
def test_check_dmi_files_google(mock_open_file):
    """Test reading google content from DMI files."""
    mock_file = MagicMock()
    mock_file.read.return_value = "Google Compute Engine"
    mock_open_file.return_value.__enter__.return_value = mock_file
    assert provider.check_dmi_files() == provider.PROVIDER_GOOGLE
