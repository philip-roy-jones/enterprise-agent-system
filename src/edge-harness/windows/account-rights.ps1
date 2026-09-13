# Installer-only local account rights. Never exposed as an agent capability.
if (-not ('EASAccountRights' -as [type])) {
Add-Type @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class EASAccountRights {
 [StructLayout(LayoutKind.Sequential)] struct ObjectAttributes {
  public uint Length; public IntPtr RootDirectory, ObjectName; public uint Attributes;
  public IntPtr SecurityDescriptor, SecurityQualityOfService;
 }
 [StructLayout(LayoutKind.Sequential)] struct UnicodeString {
  public ushort Length, MaximumLength; public IntPtr Buffer;
 }
 [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(IntPtr name, ref ObjectAttributes attrs, uint access, out IntPtr handle);
 [DllImport("advapi32.dll")] static extern uint LsaAddAccountRights(IntPtr handle, byte[] sid, UnicodeString[] rights, uint count);
 [DllImport("advapi32.dll")] static extern uint LsaRemoveAccountRights(IntPtr handle, byte[] sid, bool all, UnicodeString[] rights, uint count);
 [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr handle);
 [DllImport("advapi32.dll")] static extern uint LsaNtStatusToWinError(uint status);
 public static void Set(byte[] sid, string right, bool remove) {
  var attrs = new ObjectAttributes(); attrs.Length = (uint)Marshal.SizeOf(attrs);
  IntPtr policy; uint status = LsaOpenPolicy(IntPtr.Zero, ref attrs, 0x810, out policy);
  if (status != 0) throw new Win32Exception((int)LsaNtStatusToWinError(status));
  var value = new UnicodeString { Length=(ushort)(right.Length*2), MaximumLength=(ushort)((right.Length+1)*2), Buffer=Marshal.StringToHGlobalUni(right) };
  try {
   status = remove ? LsaRemoveAccountRights(policy, sid, false, new[]{value}, 1) : LsaAddAccountRights(policy, sid, new[]{value}, 1);
   if (status != 0) throw new Win32Exception((int)LsaNtStatusToWinError(status));
  } finally { Marshal.FreeHGlobal(value.Buffer); LsaClose(policy); }
 }
}
'@
}
function Set-EasAccountRight([string]$Sid, [string]$Right, [bool]$Remove=$false) {
    $identity = New-Object Security.Principal.SecurityIdentifier($Sid)
    $bytes = New-Object byte[] $identity.BinaryLength
    $identity.GetBinaryForm($bytes, 0)
    [EASAccountRights]::Set($bytes, $Right, $Remove)
}
