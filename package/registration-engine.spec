#
# spec file for package cloud-registration-engine
#
# Copyright (c) 2026 SUSE LLC
#
# All modifications and additions to the file contributed by third parties
# remain the property of their copyright owners, unless otherwise agreed
# upon. The license for this file, and modifications and additions to the
# file, is the same license as for the pristine package itself (unless the
# license for the pristine package is not an Open Source License, in which
# case the license is the MIT License). An "Open Source License" is a
# license that conforms to the Open Source Definition (Version 1.9)
# published by the Open Source Initiative.

# Please submit bugfixes or comments via https://bugs.opensuse.org/
#

%if 0%{?suse_version} >= 1600
%define pythons %{primary_python}
%else
%{?sle15_python_module_pythons}
%endif
%global _sitelibdir %{%{pythons}_sitelib}

Name:           cloud-registration-engine
Version:        0.1.0
Release:        0
Summary:        Provide zero-touch registration and compliance experience for PAYG deployments
License:        GPL-3.0-or-later
Group:          Development/Languages/Python
URL:            https://github.com/SUSE-Enceladus/%{name}
Source:         registration_engine-%{version}.tar.gz
BuildRequires:  python-rpm-macros
BuildRequires:  fdupes
BuildRequires:  %{pythons}-pytest
BuildRequires:  %{pythons}-coverage
BuildRequires:  %{pythons}-pytest-cov
BuildRequires:  %{pythons}-pip
BuildRequires:  %{pythons}-setuptools
BuildRequires:  %{pythons}-wheel
BuildRequires:  %{pythons}-poetry-core
BuildRequires:  %{pythons}-lxml
BuildRequires:  %{pythons}-requests
BuildRequires:  cloud-regionsrv-client
Requires:       %{pythons}-lxml
Requires:       %{pythons}-requests
Requires:       cloud-regionsrv-client
BuildArch:      noarch

%description
The primary objective of the Registration Engine is to provide a seamless,
zero-touch registration and compliance experience for Pay-As-You-Go (PAYG)
deployments originating from a cloud marketplace.

By automating the credential exchange and state management between Azure's
billing APIs and the product ecosystem, this architecture ensures that the
deployment remains fully compliant and connected without requiring manual
intervention from the cluster administrator.

%prep
%autosetup -p1 -n registration_engine-%{version}

%build
%pyproject_wheel

%install
%pyproject_install
%fdupes %{buildroot}%{_sitelibdir}

%check
export PYTHONPATH=%{buildroot}%{_sitelibdir}
%{python_expand $python -m pytest}

%files
%defattr(-,root,root)
%license LICENSE
%doc README.md
%{_bindir}/registration-engine
%{_sitelibdir}/registration_engine/
%{_sitelibdir}/registration_engine-*.dist-info/

%changelog
