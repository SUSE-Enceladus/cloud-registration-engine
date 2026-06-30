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
def test_check_azure_imds(mock_check_endpoint):
    """Test Azure IMDS check."""
    mock_check_endpoint.return_value = (True, '')
    assert provider.check_azure_imds() is True


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_gcp_imds(mock_check_endpoint):
    """Test GCP IMDS check."""
    mock_check_endpoint.return_value = (True, '')
    assert provider.check_gcp_imds() is True


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_aws_imds_v2_success(mock_check_endpoint):
    """Test AWS IMDSv2 success (token works)."""
    mock_check_endpoint.side_effect = [(True, 'fake_token'), (True, '')]

    assert provider.check_aws_imds() is True
    assert mock_check_endpoint.call_count == 2


@patch('registration_engine.provider.check_imds_endpoint')
def test_check_aws_imds_v1_fallback(mock_check_endpoint):
    """Test AWS IMDSv2 failure falling back to IMDSv1."""
    mock_check_endpoint.side_effect = [(False, ''), (True, '')]

    assert provider.check_aws_imds() is True
    assert mock_check_endpoint.call_count == 2


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
