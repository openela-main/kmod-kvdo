%global commit                  c9bd224d9c48b35f3db202e648c3abaece81f39e
%global gittag                  8.2.1.6
%global shortcommit             %(c=%{commit}; echo ${c:0:7})
%define spec_release            98

%define kmod_name		kvdo
%define kmod_driver_version	%{gittag}
%define kmod_rpm_release	%{spec_release}
%define kmod_kernel_version	5.14.0-360.el9
%define kmod_headers_version	%(rpm -qa kernel-devel | sed 's/^kernel-devel-//')
%define kmod_kbuild_dir		.
%define kmod_devel_package	0

Source0:	https://github.com/dm-vdo/%{kmod_name}/archive/%{commit}/%{kmod_name}-%{shortcommit}.tar.gz
Patch0:         add_lz4_dependency.patch
Patch1:         removed-logical-space-check-from-table-line.patch

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

BuildRequires:  libuuid-devel
BuildRequires:  redhat-rpm-config
ExcludeArch:    i686
ExcludeArch:    ppc
ExcludeArch:    ppc64
ExcludeArch:    s390

%global kernel_source() /usr/src/kernels/%{kmod_headers_version}

%global _use_internal_dependency_generator 0
Provides:         kmod-%{kmod_name} = %{?epoch:%{epoch}:}%{version}-%{release}
Requires(post):   %{_sbindir}/weak-modules
Requires(postun): %{_sbindir}/weak-modules
Requires:         kernel-core-uname-r    >= %{kmod_kernel_version}
Requires:         kernel-modules-uname-r >= %{kmod_kernel_version}

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
printf '%s\n' "${modules[@]}" >> /usr/lib/rpm-kmod-posttrans-weak-modules-add

%pretrans -p <lua>
posix.unlink("/usr/lib/rpm-kmod-posttrans-weak-modules-add")

%posttrans
if [ -f "/usr/lib/rpm-kmod-posttrans-weak-modules-add" ]; then
	modules=( $(cat /usr/lib/rpm-kmod-posttrans-weak-modules-add) )
	rm -rf /usr/lib/rpm-kmod-posttrans-weak-modules-add
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
%patch0 -p1
%patch1 -p1
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
* Thu Aug 24 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-98.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Mon Jul 31 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-97.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Fri Jul 21 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-96.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Tue Jul 18 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-95.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Wed Jul 12 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-94.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Wed Jul 05 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-93.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Tue Jun 27 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-92.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Tue Jun 20 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-91.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Wed Jun 14 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-90.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Mon Jun 12 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-89.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Tue May 30 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-88.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Tue May 23 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-87.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Fri May 19 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-86.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Wed May 17 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-85.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Thu May 11 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-84.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Thu May 04 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-83.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Mon May 01 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-82.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Tue Apr 25 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-81.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Fri Apr 14 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-80.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Tue Apr 11 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-79.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Mon Apr 03 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-78.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Thu Mar 30 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-77.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Mon Mar 20 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-76.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Mon Mar 13 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-75.el9
- Rebuilt for latest kernel.
- Related: rhbz#2172911

* Mon Feb 27 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-74.el9
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Tue Feb 21 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-73.el9
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Tue Feb 14 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.6-72.el9
- Fixed bug in read-only rebuild when the logical size of the volume is an
  exact multiple of 821 4K blocks.
- Resolves: rhbz#2166132

* Thu Feb 09 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.3-72.el9
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Wed Feb 01 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.3-71.el9
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Mon Jan 30 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.3-70.el9
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Mon Jan 23 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.3-69.el9
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Fri Jan 13 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.3-68.el9
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Fri Jan 13 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.3-67.el9
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Wed Jan 04 2023 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.3-66.el9
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Thu Dec 22 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.3-65.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Thu Dec 15 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.3-64.el9_2
- Added a check for 0 length table line arguments.
- Resolves: rhbz#2142084

* Mon Dec 12 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.2-64.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Wed Dec 07 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.2-63.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Mon Nov 28 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.2-62.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Tue Nov 22 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.2-61.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Fri Nov 18 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.2-60.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Tue Nov 15 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.1.2-59.el9_2
- Adapted to backported kernel changes.
- Resolves: rhbz#2139179

* Fri Nov 11 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-59.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Wed Nov 9 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-58.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Tue Nov 8 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-57.el9_2
- Rebuilt for latest kernel.
- Related: RHELPLAN-131751

* Mon Nov 7 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-56.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Thu Nov 3 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-55.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Mon Oct 31 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-54.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Thu Oct 27 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-53.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Wed Oct 26 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-52.el9_2
- Temporarily patched to remove bdevname usage and correct build failure.
- Related: rhbz#2119820

* Wed Oct 26 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-52.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Mon Oct 17 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-51.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Wed Oct 12 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-50.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Wed Sep 28 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-49.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Fri Sep 23 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-48.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Mon Sep 19 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.18-47.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820
- Adjust scriplets that use /var/lib to use /usr/lib for ostree environments.
- Resolves: rhbz#2105013

* Tue Sep 13 2022 - Andy Walsh <awalsh@redhat.com> - 8.2.0.18-46.el9_2
- Rebuilt for latest kernel.
- Related: rhbz#2119820

* Wed Aug 24 2022 - Andy Walsh <awalsh@redhat.com> - 8.2.0.18-46
- Temporarily dropped a check that validates the logical size specified from
  the table line.
- Related: rhbz#2071648

* Tue Aug 23 2022 - Andy Walsh <awalsh@redhat.com> - 8.2.0.18-45
- Fixed a race handling timeouts of dedupe requests.
- Resolves: rhbz#2115504

* Tue Aug 23 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.2-45
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Thu Aug 18 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.2.0.2-44
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Wed Aug 10 2022 - Chung Chung <cchung@redhat.com> - 8.2.0.2-43
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Wed Jul 27 2022 - Andy Walsh <awalsh@redhat.com> - 8.2.0.2-42
- Added missing lz4 libs to rebased code
- Resolves: rhbz#2071648

* Tue Jul 19 2022 - Andy Walsh <awalsh@redhat.com> - 8.2.0.2-41
- Rebased to latest upstream candidate.
- Resolves: rhbz#2071648

* Sat Jul 16 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.1.1.371-41
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Fri Jul 15 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.1.1.371-40
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Mon Jul 11 2022 - Chung Chung <cchung@redhat.com> - 8.1.1.371-39
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Tue Jul 05 2022 - Chung Chung <cchung@redhat.com> - 8.1.1.371-38
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Mon Jul 04 2022 - Chung Chung <cchung@redhat.com> - 8.1.1.371-37
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Tue Jun 28 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.1.1.371-36
- TEMPORARY FIX to correct build failures regarding bio_reset(), __bio_clone_fast(), and bio_init().
- Related: rhbz#2060486

* Tue Jun 28 2022 - Susan LeGendre-McGhee <slegendr@redhat.com> - 8.1.1.371-36
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Sun Jun 26 2022 - Chung Chung <cchung@redhat.com> - 8.1.1.371-35
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Wed Jun 15 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.371-34
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Tue Jun 07 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.371-33
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Wed Jun 01 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.371-32
- Rebased to newer version.
- Related: rhbz#2071648

* Tue May 31 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-32
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Sat May 28 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-31
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Mon May 23 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-30
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Mon May 16 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-29
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Fri May 13 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-28
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Thu May 12 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-27
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Tue May 10 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-26
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Sat May 07 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-25
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Thu May 05 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-24
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Wed May 04 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-23
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Fri Apr 29 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-22
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Fri Apr 22 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-21
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Thu Apr 21 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-20
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Wed Apr 13 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-19
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Mon Apr 11 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-18
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Mon Mar 28 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-17
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Mon Mar 21 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-16
- Rebuilt for latest kernel.
- Related: rhbz#2060486

* Mon Feb 28 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-15
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Mon Feb 21 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-14
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Wed Feb 16 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-13
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Sat Feb 12 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.360-12
- Fixed a compilation issue due to changes in stdarg.h.
- Resolves: rhbz#2035003
- Modified the UDS index to handle backing store changes while suspended.
- Resolves: rhbz#2007803
- Fixed a bug which prevented the resumption of a suspended read-only vdo.
- Resolves: rhbz#2004206

* Thu Feb 03 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.287-12
- Adjusted kernel dependencies to grab the right packages.
- Resolves: rhbz#2022464
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Mon Jan 31 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.287-11
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Sun Jan 23 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.1.287-10
- Eliminated uses of "master" as part of the conscious language initiative.
- Resolves: rhbz#2023970
- Fixed potential use-after-free error found by Coverity.
- Resolves: rhbz#1999056
- Fixed bug which could result in empty flushes being issued to the storage
  below vdo while suspended.
- Resolves: rhbz#2013057
- Added optional table line parameters for enabling or disabling
  deduplication and compression.
- Resolves: rhbz#2007444
- Adapted to kernel API changes.
- Resolves: rhbz#2035003

* Thu Jan 06 2022 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-10
- Rebuilt for latest kernel.
- Related: rhbz#2000926
- Temporarily disabled creation of sysfs nodes.
- Related: rhbz#2035003

* Sun Dec 19 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-9
- Rebuilt for latest kernel.
- Related: rhbz#2000926
- Stopped using bvec_kmap_irq as it has been removed.
- Removed usage of removed elevator constants
- Resolves: rhbz#2035003

* Wed Dec 15 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-8
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Tue Dec 07 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-7
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Tue Dec 07 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-6
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Thu Nov 11 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-5
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Wed Oct 13 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-4
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Thu Sep 30 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-3
- Rebuilt for latest kernel.
- Related: rhbz#2000926

* Mon Aug 09 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-2
- Rebased to upstream candidate.
- Resolves: rhbz#1955374

* Mon Aug 09 2021 Mohan Boddu <mboddu@redhat.com> - 8.1.0.316-1.1
- Rebuilt for IMA sigs, glibc 2.34, aarch64 flags
  Related: rhbz#1991688

* Sat Aug 07 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.316-1
- Rebased to upstream candidate.
- Resolves: rhbz#1955374

* Thu Jul 29 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.264-1
- Rebased to upstream candidate.
- Related: rhbz#1955374
- Fixed GCC implicit-fallthrough errors when building for latest kernel
- Resolves: rhbz#1984814

* Tue May 04 2021 - Andy Walsh <awalsh@redhat.com> - 8.1.0.4-1
- Initial build for EL9
- Related: rhbz#1955374
