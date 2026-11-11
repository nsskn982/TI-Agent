import 'package:flutter/material.dart';
import 'package:font_awesome_flutter/font_awesome_flutter.dart';

import '../config.dart';
import '../models.dart';
import 'citation_sheet.dart';

class ContactLink {
  const ContactLink(this.label, this.icon, this.url);

  final String label;
  final FaIconData icon; // font_awesome_flutter 11: its own type, drawn with FaIcon (not Icon)
  final String url;
}

/// LinkedIn and GitHub, each shown only if its URL is set and http(s).
List<ContactLink> contactLinks({String linkedin = AppConfig.linkedinUrl, String github = AppConfig.githubUrl}) => [
      if (safeUrl(linkedin) case final u?) ContactLink('LinkedIn', FontAwesomeIcons.linkedin, u),
      if (safeUrl(github) case final u?) ContactLink('GitHub', FontAwesomeIcons.github, u),
    ];

/// App-bar "Contact" button: opens a small sheet with the two logos.
class ContactButton extends StatelessWidget {
  const ContactButton({super.key});

  @override
  Widget build(BuildContext context) {
    final links = contactLinks();
    if (links.isEmpty) return const SizedBox.shrink();
    return TextButton(
      onPressed: () => showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Padding(padding: EdgeInsets.only(bottom: 4), child: Text('Get in touch')),
            for (final l in links)
              ListTile(
                leading: FaIcon(l.icon),
                title: Text(l.label),
                trailing: const Icon(Icons.open_in_new, size: 18),
                onTap: () => openExternal(context, l.url),
              ),
            const SizedBox(height: 8),
          ]),
        ),
      ),
      child: const Text('Contact'),
    );
  }
}

/// Big buttons for the closing scene.
class ContactButtons extends StatelessWidget {
  const ContactButtons({super.key});

  @override
  Widget build(BuildContext context) {
    return Wrap(alignment: WrapAlignment.center, spacing: 12, runSpacing: 12, children: [
      for (final l in contactLinks())
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          ),
          onPressed: () => openExternal(context, l.url),
          icon: FaIcon(l.icon, size: 22),
          label: Text(l.label, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        ),
    ]);
  }
}
