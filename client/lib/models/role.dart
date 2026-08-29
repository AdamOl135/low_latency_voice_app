import '../core/constants.dart';

/// Role and permission definitions.
class Role {
  final int id;
  final String name;
  final int permissions;
  final int position;
  final bool isDefault;

  const Role({
    required this.id,
    required this.name,
    required this.permissions,
    this.position = 0,
    this.isDefault = false,
  });

  factory Role.fromJson(Map<String, dynamic> json) {
    return Role(
      id: json['id'] is int ? json['id'] as int : 0,
      name: (json['name'] as String?) ?? '',
      permissions: (json['permissions'] is int) ? json['permissions'] as int : 0,
      position: (json['position'] is int) ? json['position'] as int : 0,
      isDefault: json['is_default'] == true,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'permissions': permissions,
      'position': position,
      'is_default': isDefault,
    };
  }

  /// Helper to check permissions. Admin bit (0x01) bypasses all permission checks.
  static bool hasPermission(int effectivePerms, int requiredPerm) {
    if ((effectivePerms & AppConstants.permAdmin) == AppConstants.permAdmin) {
      return true;
    }
    return (effectivePerms & requiredPerm) == requiredPerm;
  }
}
