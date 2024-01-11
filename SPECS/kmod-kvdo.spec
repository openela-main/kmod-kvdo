%global commit                  c3fab428a1fdc02cb0d5f4bba7e88ec94056e96f
%global gittag                  6.2.8.7
%global shortcommit             %(c=%{commit}; echo ${c:0:7})
%define spec_release            92

%define kmod_name		kvdo
%define kmod_driver_version	%{gittag}
%define kmod_rpm_release	%{spec_release}
%define kmod_kernel_version	4.18.0-507.el8
%define kmod_headers_version	%(rpm -qa kernel-devel | sed 's/^kernel-devel-//')
%define kmod_kbuild_dir		.
%define kmod_dependencies       %{nil}
%define kmod_build_dependencies	%{nil}
%define kmod_devel_package	0

Source0:	https://github.com/dm-vdo/%{kmod_name}/archive/%{commit}/%{kmod_name}-%{shortcommit}.tar.gz

%define findpat %( echo "%""P" )

Name:		kmod-kvdo
Version:	%{kmod_driver_version}
Release:	%{kmod_rpm_release}%{?dist}
Summary:	Kernel Modules for Virtual Data Optimizer
License:	GPLv2+
URL:		http://github.com/dm-vdo/kvdo
BuildRoot:	%(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)
BuildRequires:  elfutils-libelf-devel
BuildRequires:	glibc
BuildRequires:	kernel-devel >= %{kmod_kernel_version}

# Disable the kernel-debug requirement for now
%if 0
# kernel-debug appears to not be necessary at the moment. 
BuildRequires:  kernel-debug >= %{kmod_kernel_version}
%endif

BuildRequires:  libuuid-devel
BuildRequires:  redhat-rpm-config
ExcludeArch:    i686
ExcludeArch:    ppc
ExcludeArch:    ppc64
ExcludeArch:    s390

%global kernel_source() /usr/src/kernels/%{kmod_headers_version}

%global _use_internal_dependency_generator 0
Provides:         kernel-modules = %{kmod_kernel_version}.%{_target_cpu}
Provides:         kmod-%{kmod_name} = %{?epoch:%{epoch}:}%{version}-%{release}
Requires(post):   %{_sbindir}/weak-modules
Requires(postun): %{_sbindir}/weak-modules
Requires:         kernel-core-uname-r    >= %{kmod_kernel_version}
Requires:         kernel-modules-uname-r >= %{kmod_kernel_version}

%if "%{kmod_build_dependencies}" != ""
BuildRequires:  %{kmod_build_dependencies}
%endif
%if "%{kmod_dependencies}" != ""
Requires:       %{kmod_dependencies}
%endif

%description
Virtual Data Optimizer (VDO) is a device mapper target that delivers
block-level deduplication, compression, and thin provisioning.

This package provides the kernel modules for VDO.

%pre
# During the install, check whether kvdo or uds is loaded.  A warning here
# indicates that a previous install was not completely removed.  This message
# is purely informational to the user.
for module in kvdo uds; do
  if grep -q "^${module}" /proc/modules; then
    if [ "${module}" == "kvdo" ]; then
      echo "WARNING: Found ${module} module previously loaded (Version: $(cat /sys/kvdo/version 2>/dev/null || echo Unknown)).  A reboot is recommended before attempting to use the newly installed module."
    else
      echo "WARNING: Found ${module} module previously loaded.  A reboot is recommended before attempting to use the newly installed module."
    fi
  fi
done

%post
modules=( $(find /lib/modules/%{kmod_headers_version}/extra/kmod-%{kmod_name} | grep '\.ko$') )
printf '%s\n' "${modules[@]}" >> /var/lib/rpm-kmod-posttrans-weak-modules-add

%pretrans -p <lua>
posix.unlink("/var/lib/rpm-kmod-posttrans-weak-modules-add")

%posttrans
if [ -f "/var/lib/rpm-kmod-posttrans-weak-modules-add" ]; then
	modules=( $(cat /var/lib/rpm-kmod-posttrans-weak-modules-add) )
	rm -rf /var/lib/rpm-kmod-posttrans-weak-modules-add
	printf '%s\n' "${modules[@]}" | %{_sbindir}/weak-modules --dracut=/usr/bin/dracut --add-modules
fi

%preun
rpm -ql kmod-kvdo-%{kmod_driver_version}-%{kmod_rpm_release}%{?dist}.$(arch) | grep '\.ko$' > /var/run/rpm-kmod-%{kmod_name}-modules
# Check whether kvdo or uds is loaded, and if so attempt to remove it.  A
# failure to unload means there is still something using the module.  To make
# sure the user is aware, we print a warning with recommended instructions.
for module in kvdo uds; do
  if grep -q "^${module}" /proc/modules; then
    warnMessage="WARNING: ${module} in use.  Changes will take effect after a reboot."
    modprobe -r ${module} 2>/dev/null || echo ${warnMessage} && /usr/bin/true
  fi
done

%postun
modules=( $(cat /var/run/rpm-kmod-%{kmod_name}-modules) )
rm /var/run/rpm-kmod-%{kmod_name}-modules
printf '%s\n' "${modules[@]}" | %{_sbindir}/weak-modules --dracut=/usr/bin/dracut --remove-modules

%files
%defattr(644,root,root,755)
/lib/modules/%{kmod_headers_version}
/etc/depmod.d/%{kmod_name}.conf
/usr/share/doc/kmod-%{kmod_name}/greylist.txt

%prep
%setup -n %{kmod_name}-%{commit}
%{nil}
set -- *
mkdir source
mv "$@" source/
mkdir obj

%build
rm -rf obj
cp -r source obj
make -C %{kernel_source} M=$PWD/obj/%{kmod_kbuild_dir} V=1 \
	NOSTDINC_FLAGS="-I $PWD/obj/include -I $PWD/obj/include/uapi"
# mark modules executable so that strip-to-file can strip them
find obj/%{kmod_kbuild_dir} -name "*.ko" -type f -exec chmod u+x '{}' +

whitelist="/lib/modules/kabi-current/kabi_whitelist_%{_target_cpu}"

for modules in $( find obj/%{kmod_kbuild_dir} -name "*.ko" -type f -printf "%{findpat}\n" | sed 's|\.ko$||' | sort -u ) ; do
	# update depmod.conf
	module_weak_path=$(echo $modules | sed 's/[\/]*[^\/]*$//')
	if [ -z "$module_weak_path" ]; then
		module_weak_path=%{name}
	else
		module_weak_path=%{name}/$module_weak_path
	fi
	echo "override $(echo $modules | sed 's/.*\///') $(echo %{kmod_headers_version} | sed 's/\.[^\.]*$//').* weak-updates/$module_weak_path" >> source/depmod.conf

	# update greylist
	nm -u obj/%{kmod_kbuild_dir}/$modules.ko | sed 's/.*U //' |  sed 's/^\.//' | sort -u | while read -r symbol; do
		grep -q "^\s*$symbol\$" $whitelist || echo "$symbol" >> source/greylist
	done
done
sort -u source/greylist | uniq > source/greylist.txt

%install
export INSTALL_MOD_PATH=$RPM_BUILD_ROOT
export INSTALL_MOD_DIR=extra/%{name}
make -C %{kernel_source} modules_install V=1 \
	M=$PWD/obj/%{kmod_kbuild_dir}
# Cleanup unnecessary kernel-generated module dependency files.
find $INSTALL_MOD_PATH/lib/modules -iname 'modules.*' -exec rm {} \;

install -m 644 -D source/depmod.conf $RPM_BUILD_ROOT/etc/depmod.d/%{kmod_name}.conf
install -m 644 -D source/greylist.txt $RPM_BUILD_ROOT/usr/share/doc/kmod-%{kmod_name}/greylist.txt

%clean
rm -rf $RPM_BUILD_ROOT

%changelog
* Thu Aug 03 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.8.7-92
- Rebuilt for latest 4.18 kernel.
- Related: rhbz#2173037

* Thu Apr 27 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.8.7-91
- Rebuilt for latest 4.18 kernel.
- Related: rhbz#2173037

* Wed Apr 12 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.8.7-90
- Rebuilt for latest 4.18 kernel.
- Related: rhbz#2173037

* Wed Mar 22 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.8.7-89
- Rebuilt for latest 4.18 kernel.
- Related: rhbz#2173037

* Tue Feb 14 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.8.7-88
- Fixed bug in read-only rebuild when the logical size of the volume is an
  exact multiple of 821 4K blocks.
- Resolves: rhbz#2166131

* Fri Dec 16 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.8.6-88
- Added a check for 0 length table line arguments.
- Resolves: rhbz#2142080

* Wed Nov 16 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.8.4-88
- Rebuilt for latest 4.18 kernel.
- Related: rhbz#2119819

* Tue Nov 15 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.8.4-87
- Adapted to backported kernel changes.
- Resolves: rhbz#2139242

* Mon Sep 26 2022 - Andy Walsh <awalsh@redhat.com> - 6.2.8.1-87
- Fixed a bug which could produce a deadlock after multiple saves and resumes
  of a vdo.
- Resolves: rhbz#2109047

* Thu Aug 11 2022 - Andy Walsh <awalsh@redhat.com> - 6.2.7.17-87
- Rebuilt for latest 4.18 kernel.
- Related: rhbz#2060475

* Mon Jul 18 2022 - Andy Walsh <awalsh@redhat.com> - 6.2.7.17-86
- Fixed bug which could result in empty flushes being issued to the storage
  below vdo while suspended.
- Resolves: rhbz#2013056
- Fixed syntax mismatch which prevented lvm from being able to configure a
  512MB UDS index.
- Resolves: rhbz#2073203
- Fixed a race handling timeouts of dedupe index queries.
- Resolves: rhbz#2092075

* Mon Jul 11 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.6.14-86
- Rebuild for latest 4.18 kernel.
- Related: rhbz#2060475

* Thu Jul 07 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 6.2.6.14-85
- Bumped NVR for new 4.18 kernel.
- Related: rhbz#2060475

* Fri Feb 11 2022 - Andy Walsh <awalsh@redhat.com> - 6.2.6.14-83
- Fixed stack frame warnings when building with the debug kernel.
- Resolves: rhbz#1767236

* Thu Feb 03 2022 - Andy Walsh <awalsh@redhat.com> - 6.2.6.3-83
- Adjusted kernel dependencies to grab the right packages.
- Resolves: rhbz#2011426
- Rebuilt for latest kernel.
- Relates: rhbz#2000909

* Wed Nov 03 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.6.3-82
- Fixed a bug which prevented the resumption of a suspended read-only vdo.
- Resolves: rhbz#1996893

* Mon Oct 11 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.72-81.8_6
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#2000909

* Fri Aug 27 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.72-80
- Bumped NVR for new 4.18 kernel
- Related: rhbz#1939279

* Tue Aug 10 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.72-79
- Fixed a bug which could result in the UDS index issuing I/O while
  suspended.
- Resolves: rhbz#1990180

* Thu Aug 05 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.71-79
- Reduced context switches when a vdo is idle.
- Resolves: rhbz#1886738

* Thu Jul 22 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.65-79
- Removed unneeded allocations from the previous fixes for rebuilding
  a converted index.
- Resolves: rhbz#1966824

* Thu Jul 15 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.62-79
- Fixed chapter computation for a converted sparse index.
- Resolves: rhbz#1965516
- Fixed invalidation of converted chapters.
- Resolves: rhbz#1966818
- Removed extraneous fields from the super block of a converted index.
- Resolves: rhbz#1965546
- Fixed calculation of the number of expiring chapters in a converted
  index.
- Resolves: rhbz#1975546
- Fixed bugs rebuilding a converted index.
- Resolves: rhbz#1966824

* Mon Jun 21 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.41-79
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1939279

* Tue Jun 01 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.41-78
- Fixed bugs in reading the UDS index of a VDO volume which was converted
  to LVM.
- Resolves: rhbz#1928284

* Thu May 20 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.21-78
- Added support for VDO volumes which have been converted to LVM.
- Related: rhbz#1928284

* Thu May 13 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.5.11-78
- Introduced new memory size parameter values for UDS indexes which have
  been converted from vdo script management to LVM.
- Resolves: rhbz#1928284

* Tue Mar 16 2021 - Andy Walsh <awalsh@redhat.com> - 6.2.4.26-77.8_5
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1939279

* Sat Nov 28 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.4.26-76
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1894978

* Thu Nov 05 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.4.26-75
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1894978

* Mon Nov 02 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.4.26-74
- Modified physical growth to validate the new VDO size against the size of
  the underlying storage.
- Resolves: rhbz#1732922
- Fixed issues which prevented lvrename from working on lvm managed
  VDO devices.
- Resolves: rhbz#1888419

* Thu Oct 01 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.4.14-74
- Fixed a bug which causes the UDS index to consume an excessive
  number of CPU cycles when the VDO device is idle.
- Resolves: rhbz#1870660

* Thu Jul 16 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.3.107-74
- Updated dependencies to prevent installing kernel-rt incorrectly.
- Resolves: rhbz#1811923
- Bumped requirement for new 4.18 kernel
- Relates: rhbz#1812069

* Fri Jun 19 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.3.107-73
- Fixed a bug which can cause a soft lockup if users interrupt processes
  waiting on dm-setup commands.
- Resolves: rhbz#1844651
- Fixed a rare race which could cause a suspend of a VDO device to fail.
- Resolves: rhbz#1847747

* Tue Jun 02 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.3.91-73
- Removed unused UDS bio statistics.
- Resolves: rhbz#1827762
- Removed support for old kernels.
- Resolves: rhbz#1827762
- Fixed Coverity errors.
- Resolves: rhbz#1827763
- Improved the error message when slab journal locks overflow.
- Resolves: rhbz#1827761
- Fixed a bug which could result in VDO issuing I/O while suspended.
- Resolves: rhbz#1824789
- Fixed a rare double-enqueue bug in the recovery journal.
- Resolves: rhbz#1824802
- Modified VDO to not allocate an index if the VDO device is started
  with deduplication disabled.
- Resolves: rhbz#1755448
- Nodified VDO to not log spurious journal lock warnings when cleaning up
  write requests which failed due to the VDO going read-only.
- Resolves: rhbz#1840455

* Mon Apr 27 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117_8.3-73
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1812069

* Mon Apr 27 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117_8.3-72
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1812069

* Fri Apr 17 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117_8.3-71
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1812069

* Fri Apr 17 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117_8.3-70
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1812069

* Wed Mar 25 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117_8.3-69
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1812069

* Wed Mar 11 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117-68
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1812069

* Tue Mar 10 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117-67
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1812069

* Tue Mar 10 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117-66
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1812069

* Sat Mar 07 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117-65
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1764816

* Tue Feb 11 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.117-63
- Fixed a bug which would cause the UDS index to be perceived as corrupt
  when a VDO volume is moved to a system with a different endianness.
- Resolves: rhbz#1745211
- Modified UDS index rebuild to be interruptible so that shutting down a
  VDO whose index is rebuilding need not wait for the index rebuild to
  complete.
- Resolves: rhbz#1737639
- Prevented two VDO devices from being started on the same storage.
- Resolves: rhbz#1725052
- Fixed rare races which could result in VDO issuing I/O while suspended.
- Resolves: rhbz#1766358
- Fixed crashes when re-suspending a VDO after it had been resumed.
- Resolves: rhbz#1765253
- Made async mode ACID. Added async-unsafe mode to preserve the performance of
  the old implementation.
- Resolves: rhbz#1657301

* Tue Jan 14 2020 - Andy Walsh <awalsh@redhat.com> - 6.2.2.24-63
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1764816

* Tue Dec 03 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.2.24-62
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1764816

* Tue Nov 26 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.2.24-61
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1764816

* Mon Nov 11 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.2.24-60
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1764816

* Thu Oct 31 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.2.24-59
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1764816

* Wed Oct 30 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.2.24-58
- Incremented the dm target version to allow lvm to tell whether a VDO
- Resolves: rhbz#1752893

* Thu Oct 24 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.2.18-58
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1764816

* Thu Oct 17 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.2.18-57
- Reduced the default number of index zones as the previous default
  attempted to maximize index performance at the expense of all other
  processes.
- Resolves: rhbz#1703507
- Fixed an assertion when resuming a VDO device which was not suspended
  with the no-flush flag.
- Resolves: rhbz#1752893

* Fri Sep 13 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.138-57
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1695330

* Thu Aug 08 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.138-56
- Fixed a crash on allocation failure and a use-after-free race introduced by
  the changes to avoid issuing I/O while suspended.
- Resolves: rhbz#1659303

* Fri Aug 02 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.134-56
- Finished converting the VDO device to conform to the DM convention of not
  issuing I/O while suspended.
- Resolves: rhbz#1659303
- Fixed a bug where crash recovery could use the wrong threads for certain
  operations potentially resulting in memory corruption.
- Resolves: rhbz#1703621
- Fixed a bug which could cause segfaults when running the vdostatus
  command.
- Resolves: rhbz#1669960
- Eliminated a backtrace from the error logged when creating a VDO device
  with an erroneous physical size in the table line.
- Resolves: rhbz#1717435
- Fixed a possible use-after-free of the UDSConfiguration.
- Resolves: rhbz#1653802
- Made VDO a singleton device because multi-segment devices containing a
  VDO have a number of issues.
- Resolves: rhbz#1725077
- Converted the VDO device to conform to the DM convention of not issuing
  writes from the constructor.
- Resolves: rhbz#1669086

* Mon Jul 29 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.102-56
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1695330

* Fri Jul 12 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.102-55
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1695330

* Thu Jun 27 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.102-54
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1695330

* Fri Jun 14 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.102-53
- Continued converting the VDO device to conform to the DM convention of
  not issuing I/O while suspended.
  - Resolves: rhbz#1659303
- Added more rate limiting of error logging in both the kvdo and uds
  modules in order to avoid soft-lockups on newer kernels.
  - Resolves: rhbz#1703243
- Eliminated the passing of addresses of unaligned fields in packed
  - Resolves: rhbz#1718058

* Tue May 21 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.48-53
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1695330

* Tue May 21 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.48-52
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1695330

* Sun May 05 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.1.48-51
- Modified the setting of the dm target version for VDO devices to only
  change when the dm interface (i.e. table line) changes instead of tying
  it to the VDO version.
  - Resolves: rhbz#1665298
- Improved error handling when resizing VDO devices.
  - Resolves: rhbz#1659247
- Reduced, removed, and/or rate limited error logging to avoid
  soft-lockups.
  - Resolves: rhbz#1678785
  - Resolves: rhbz#1698664
- Began converting the VDO device to conform to the DM convention of not
  issuing I/O while suspended.
  - Relates: rhbz#1659303
- Added a dmsetup message to close the UDS index of a running VDO device.
  - Relates: rhbz#1643291

* Fri May 03 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-51
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1695330

* Mon Feb 25 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-50
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Fri Feb 15 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-49
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Feb 13 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-48
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Sat Feb 09 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-47
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Fri Feb 08 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-46
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Feb 06 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-45
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Jan 16 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-44
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Mon Jan 14 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-43
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Fri Jan 11 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-42
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Mon Jan 07 2019 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-41
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Dec 19 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-40
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Mon Dec 17 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-39
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Fri Dec 14 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.293-38
- Improved dmsetup error reporting of invalid thread counts.
- rhbz#1645324
- Allowed VDO backing devices to specified by device number.
- Resolves: rhbz#1594285
- Eliminated memory allocations when suspended.
- Resolves: rhbz#1658348
- Improved error handling during suspend.
- Resolves: rhbz#1658348

* Wed Dec 12 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-38
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Mon Dec 10 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-37
- Bumped NVR for driver signing
- Relates: rhbz#1589873
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Thu Nov 29 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-36
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Fri Nov 16 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.273-35
- Fixed more error path memory leaks in the uds and kvdo modules.
- Resolves: rhbz#1639854
- Removed the read cache.
- Resolves: rhbz#1639512
- Fixed a bug which prevented parsing of version 0 table lines.
- Resolves: rhbz#1643639
- In order to properly handle version 0 table lines, made no-op physical
  growth not an error.
- Resolves: rhbz#1643639
- Limited the number of logical zones to 60.
- Resolves: rhbz#1645324
- Converted to use the kernel's bio zeroing method instead of a VDO
  specific one.
- Resolves: rhbz#1647446
- Added a missing call to flush_cache_page() after writing pages which may
  be owned by the page cache or a user as required by the kernel.
- Resolves: rhbz#1647446
- Added a version 2 table line which uses DM-style optional parameters.
- Resolves: rhbz#1648469
- Fixed a bug in the statistics tracking partial I/Os.
- Resolves: rhbz#1648496
- Added a maximum discard size table line parameter and removed the
  corresponding sysfs parameter which applied to all VDO devices.
- Resolves: rhbz#1648469

* Wed Nov 07 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-35
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Oct 24 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-34
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Oct 24 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-33
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Fri Oct 19 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-32
- Depend on more of the NVR for the kernel package.
- Resolves: rhbz#1640699

* Tue Oct 16 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-31
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Tue Oct 16 2018 - Tomas Kopecek <tkopecek@redhat.com> - 6.2.0.239-30
- Bumped NVR for driver signing
- Relates: rhbz#1589873

* Mon Oct 15 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-29
- Bumped NVR for driver signing
- Relates: rhbz#1589873

* Thu Oct 11 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-28
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Oct 10 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-27
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Sun Oct 07 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.239-26
- Fixed error path memory leaks in the uds and kvdo modules.
- Resolves: rhbz#1609403
- Modified the physical and logical growth procedures to be consistent with
  other device mapper targets.
- Resolves: rhbz#1631868

* Fri Sep 28 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.219-26
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Thu Sep 27 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.219-25
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Tue Sep 25 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.219-24
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Tue Sep 25 2018 - Joseph Chapman <jochapma@redhat.com> - 6.2.0.219-23
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Mon Sep 24 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.219-22
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Fri Sep 21 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.219-21
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Thu Sep 20 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.219-20
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Sep 19 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.219-19
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Tue Sep 18 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.219-18
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Mon Sep 17 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.219-17
- Fixed error path memory leaks in the uds and kvdo modules.
- Resolves: rhbz#1609403
- Fixed conflict errors when installing RPMs via dnf.
- Resolves: rhbz#1601103
- Fixed a hang when recovering a VDO volume with a physical size larger
  than 16TB.
- Resolves: rhbz#1628316
- Fixed some potential initialization issues in the UDS module.
- Resolves: rhbz#1609403
- Fixed a use-after-free bug in a UDS error path.
- Resolves: rhbz#1609403
- Added missing va_end() calls.
- Resolves: rhbz#1627953
- Modified Makefile to take build flags from rpmbuild.
- Resolves: rhbz#1624184

* Fri Sep 14 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.197-16
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Thu Sep 13 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.197-15
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Sep 12 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.197-14
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Aug 29 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.197-13
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Wed Aug 29 2018 - Joseph Chapman <jochapma@redhat.com> - 6.2.0.197-12
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Tue Aug 28 2018 - Josh Boyer <jwboyer@redhat.com> - 6.2.0.197-11
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1623006

* Fri Aug 24 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.197-10
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1611663

* Mon Aug 20 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.197-9
- Patched a new compiler warning out
- Relates: rhbz#1611663

* Mon Aug 20 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.197-8
- Bumped NVR for new 4.18 kernel
- Relates: rhbz#1611663

* Mon Aug 13 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.197-7
- Bumped NVR for 4.18 rebase
- Resolves: rhbz#1534087

* Wed Aug  8 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.197-6
- Enabled the setting of max_discard_sectors for VDO devices via sysfs.
  This allows users stacking dm-thin devices on top of VDO to set a value which
  is large enough that dm-thin will send discards to VDO.
- Resolves: rhbz#1612349

* Sat Jul 28 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.187-6
- No longer attempt to unload modules in %preun
- Resolves: rhbz#1553420
- Fixed a bug in %preun that was attempting to call 'dnf'
- Resolves: rhbz#1598924
- Fixed weak-modules calls to use proper location for dracut
- Resolves: rhbz#1609178
- Fixed a potential deadlock in the UDS index by using the kernel supplied
  struct callback instead of our own implementation of synchronous
  callbacks.
- Eliminated obsolete code and fields from UDS.
- Converted the VDO module to use numeric.h from the UDS module instead of
  having its own version.
- Fixed a bug which would cause incorrect encoding of VDO data structures
  on disk.
- Removed or modified logging which prints pointers from the kernel since
  newer kernels obfuscate the pointer values for security reasons.
- Eliminated confusing and spurious error messages when rebuilding a UDS
  index.
- Improved memory allocation by not using the incorrect __GFP_NORETRY flag
  and by using the memalloc_noio_save mechanism.
- Finished conversion of the encoding and decoding of the VDO's on-disk
  structures to be platform independent.
- Converted VDO to use the atomic API from the UDS module instead of its
  own.
- Fixed memory leaks in UDS error paths.
- Fixed a potential stack overflow when reaping the recovery journal.

* Fri Jul 06 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.132-5
- Rebuilt to work with 4.18 kernel.

* Thu Jun 28 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.132-4
Note: This is a pre-release version, future versions of VDO may not support
VDO devices created with this version.
- Removed obsolete code.
- Continued conversion of the encoding and decoding of the VDO's on-disk
  structures to be platform independent.
- Adopted use of gcc's built-in byte order macros.
- Converted the VDO module to use the platform independent version of the
  Murmur3 hash from the UDS module.
- Improved counting of dedupe timeouts by including in the count queries
  which are not made due to their being a lack of resources from previous
  queries taking too long.
- Improved checking that VDO does not allocate memory from its own threads
  during normal operation.
- Fixed a bug which caused crashes with VDO on top of RAID-50.
- Fixed a bug which caused VDO to ignore most flush requests on kernels
  later than 4.10
- Resolves: rhbz#1594062

* Thu Jun 21 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.109-4
Note: This is a pre-release version, future versions of VDO may not support
VDO devices created with this version.
- Removed obsolete code.
- Made uses of memory barriers and atomics more portable across platforms.
- Converted the encoding and decoding of many of VDO's on-disk structures
  to be platform independent.
- Made the implementation of VDO's in-memory data structures platform
  independent.
- Fixed a logging bug which resulted in single log message being split
  across multiple log lines on newer kernels.
- Fixed a bug which would cause attempts to grow the physical size of a VDO
  device to fail if the device below the VDO was resized while the VDO was
  offline.
- Converted to use GCC's built-in macros for determining endianness.
- Converted some non-performance critical atomics to be spinlock protected
  in order to avoid dealing with memory barrier portability issues.
- Fixed a bug which could cause data loss when discarding unused portions
  of a VDO's logical space.
- Reduced memory usage (slightly) by rearranging structures to pack better
  in memory.
- Modified grow physical to fail in the prepare step if the size isn't
  changing, avoiding a suspend-and-resume cycle.
- Added support for building with a 4.18 kernel.

* Mon Jun 04 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.71-4
Note: This is a pre-release version, future versions of VDO may not support
VDO devices created with this version.
- Updated to compile on aarch64, ppc64le, and s390x processor architectures
  in addition to x86.
- Updated atomics, memory barriers, and other synchronization mechanisms to
  work on aarch64, ppc64le, and s390x processor architectures in addition
  to x86.
- Fixed thread safety issues in the UDS page cache.
- Removed obsolete code and interfaces from the UDS module.
- Added /sys/kvdo/version which contains the currently loaded version of
  the kvdo module.
- Updated the UDS module to consistently generate and encode on-disk data
  regardless of the processor architecture.
- Began Updating the VDO module to consistently encode on-disk data
  regardless of the processor architecture.
- Added logging of normal operation when a VDO device starts normally.
- Fixed a potential use-after-free race when shutting down a VDO device.
- Modified allocations made from VDO index threads to use the correct flags.
- Exported the MurmurHash3 implementation from the UDS module rather than
  having a seperate copy in the VDO module.
- Fixed handling of I/O errors in 4.13 and later kernels.
- Exported functions for handling endian conversions from the UDS module
  for use by the VDO module.

* Tue May 01 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.35-3
- Enabled aarch64 builds

* Fri Apr 27 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.35-2
Note: This is a pre-release version, future versions of VDO may not support
VDO devices created with this version.
- Added validation that the release version numbers in the geometry and
  super block match on load.
- Fixed compilation problems on newer versions of GCC.

* Tue Apr 24 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.32-2
Note: This is a pre-release version, future versions of VDO may not support
VDO devices created with this version.
- Merged the funnel queue implementations in the uds and kvdo modules.
- Improved deduplication of concurrent requests containing the same data.
- Enabled loading of VDO devices created with version 6.0 or 6.1.
- Moved atomic.h from the UDS module to the VDO module since the UDS module
  doesn't use it.
- Removed spurious error messages when first creating the index for a new
  VDO.
- Added validation that the release version numbers in the geometry block
  and VDO super block match.
- Fixed bug in UDS on architectures with page sizes larger than 4K.
- Reflected kernel change of SECTOR_SHIFT and SECTOR_SIZE from enums to
  macros.
- Continued to remove obsolete functionality from the UDS module.
- Continued to add support for architectures other than x86.
- Fixed a thread-safety issue in UDS module's chapter cache.

* Tue Apr 17 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.4-2
- Fixed path to _sbindir for weak-mldules
- Resolves: rhbz#1566144
         
* Fri Apr 13 2018 - Andy Walsh <awalsh@redhat.com> - 6.2.0.4-1
- Updated to use github for Source0
- Removed unused sections
- Initial RHEL8 RPM rhbz#1534087
         
* Fri Apr 13 2018 - J. corwin Coburn <corwin@redhat.com> - 6.2.0.4-1
- Initial pre-release for RHEL 8.
  - Please be aware that this version is not compatible with previous versions
    of VDO. Support for loading or upgrading devices created with VDO version
    6.1 will be available soon.
- Management tools will work with both python 2 and python 3.
- Dedupe path improvements.
- Beginnings of support for non-x86 architectures.
- Removed obsolete code from UDS.

* Tue Feb 27 2018 - Andy Walsh <awalsh@redhat.com> - 6.1.0.153-15
- Fixed preun handling of loaded modules
- Resolves: rhbz#1549178

* Fri Feb 16 2018 - Joseph Chapman <jochapma@redhat.com> - 6.1.0.149-13
- Sync mode is safe if underlying storage changes to requiring flushes
- Resolves: rhbz#1540777

* Wed Feb 07 2018 - Joseph Chapman <jochapma@redhat.com> - 6.1.0.146-13
- Module target is now "vdo" instead of "dedupe"
- Fixed a bug where crash recovery led to failed kernel page request
- Improved modification log messages
- Improved package description and summary fields
- Resolves: rhbz#1535127
- Resolves: rhbz#1535597
- Resolves: rhbz#1540696
- Resolves: rhbz#1541409

* Tue Feb 06 2018 - Andy Walsh <awalsh@redhat.com> - 6.1.0.144-13
- Updated summary and descriptions
- Resolves: rhbz#1541409

* Thu Feb 01 2018 - Joseph Chapman <jochapma@redhat.com> - 6.1.0.130-12
- Fix General Protection Fault unlocking UDS callback mutex
- Removing kmod-kvdo package unloads kernel module
- Fix URL to point to GitHub tree
- Resolves: rhbz#1510176
- Resolves: rhbz#1533260
- Resolves: rhbz#1539061

* Fri Jan 19 2018 - Joseph Chapman <jochapma@redhat.com> - 6.1.0.124-11
- Fixed provisional referencing for dedupe.
- Only log a bio submission from a VDO to itself.
- vdoformat cleans up metadata properly after fail.
- Resolves: rhbz#1511587
- Resolves: rhbz#1520972
- Resolves: rhbz#1532481

* Wed Jan 10 2018 - Joseph Chapman <jochapma@redhat.com> - 6.1.0.114-11
- /sys/uds permissions now resticted to superuser only
- Remove /sys/uds files that should not be used in production
- Removing kvdo module reports version
- VDO automatically chooses the proper write policy by default
- Fixed a Coverity-detected error path leak
- Resolves: rhbz#1525305
- Resolves: rhbz#1527734
- Resolves: rhbz#1527737
- Resolves: rhbz#1527924
- Resolves: rhbz#1528399

* Thu Dec 21 2017 - Joseph Chapman <jochapma@redhat.com> - 6.1.0.106-11
- Detect journal overflow after 160E of writes
- Clean up UDS threads when removing last VDO
- Resolves: rhbz#1512968
- Resolves: rhbz#1523240

* Tue Dec 12 2017 Joe Chapman <jochapma@redhat.com> 6.1.0.97-11
- Default logical size is no longer over-provisioned
- Remove debug logging when verifying dedupe advice
- Resolves: rhbz#1519330

* Fri Dec 08 2017 Joe Chapman <jochapma@redhat.com> 6.1.0.89-11
- improve metadata cleanup after vdoformat failure
- log REQ_FLUSH & REQ_FUA at level INFO
- improve performance of cuncurrent write requests with the same data
- Resolves: rhbz#1520972
- Resolves: rhbz#1521200

* Fri Dec 01 2017 Joe Chapman <jochapma@redhat.com> 6.1.0.72-10
- clear VDO metadata on a vdo remove call
- fix create of new dedupe indices
- add magic number to VDO geometry block
- do less logging when stopping a VDO
- add a UUID
- Resolves: rhbz#1512127
- Resolves: rhbz#1516081
- Resolves: rhbz#1511109
- Resolves: rhbz#1515183

* Fri Nov 17 2017 Joe Chapman <jochapma@redhat.com> 6.1.0.55-9
- fail loading an uncreated index more gracefully
- remove spurious/unnecessary files from the distribution
- fix kernel module version
- make logging less chatty
- fix an integer overflow in makeVDOLayout
- Resolves: rhbz#1511034
- Resolves: rhbz#1511109
- Resolves: rhbz#1511096

* Fri Nov 10 2017 Joe Chapman <jochapma@redhat.com> 6.1.0.44-8
- fix readCacheSize handling large numbers
- vdoformat signals error when it finds a geometry block
- prevent kernel oops when loading an old geometry block
- vdoformat silently rounds down physical sizes to a block boundary
- UDS threads identify related VDO device
- clean up contents of source tarballs
- Resolves: rhbz#1505936
- Resolves: rhbz#1507996
- Resolves: rhbz#1509466
- Resolves: rhbz#1510558
- Resolves: rhbz#1510585
- Resolves: rhbz#1511201
- Resolves: rhbz#1511209

* Fri Nov 03 2017 Joe Chapman <jochapma@redhat.com> 6.1.0.34-7
- Bugfixes
- Resolves: rhbz#1491422

* Mon Oct 30 2017 Joe Chapman <jochapma@redhat.com> 6.1.0.13-6
- Fixed some scanning tool complaints
- Resolves: rhbz#1491422

* Tue Oct 24 2017 Andy Walsh <awalsh@redhat.com> 6.1.0.0-6
- Fixed kernel requirement to allow subsequent releases without updating spec
- Resolves: rhbz#1491422

* Fri Oct 20 2017 John Wiele <jwiele@redhat.com> 6.1.0.0-5
- Bumped kernel requirement to 3.10.0-741
- Resolves: rhbz#1491422

* Tue Oct 17 2017 John Wiele <jwiele@redhat.com> 6.1.0.0-4
- Resolved some missing symbols
- Resolves: rhbz#1491422

* Mon Oct 16 2017 John Wiele <jwiele@redhat.com> 6.1.0.0-3
- Updated to provide a useable package
- Resolves: rhbz#1491422

* Sat Oct 14 2017 Andy Walsh <awalsh@redhat.com> 6.1.0.0-2
- Removed invalid requirement and some unnecessary comments in spec
- Resolves: rhbz#1491422

* Wed Oct 11 2017 John Wiele <jwiele@redhat.com> 6.1.0.0-1
- Initial vdo module for Driver Update Program
- Resolves: rhbz#1491422
